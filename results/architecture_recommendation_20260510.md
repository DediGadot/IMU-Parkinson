# Architecture Recommendation - 2026-05-10

## Objective

Find a better architecture than the current WearGait-PD codebase/model architecture under the post-leakage, post-valid-range-target rules.

## Current Architecture To Beat

- **T1 canonical floor:** `compose_t1_iter12_honest.py`, CCC `0.6550`, MAE `1.561`, N `94`.
- **T1 corrected candidate:** `run_t1_iter34_hybrid_8item_multibase.py`, hygiene-corrected CCC `0.7170`, MAE `1.7356`, N `92`; candidate only, and lower than the superseded original N=93 iter34 `0.7366`.
- **T3 canonical:** `run_t3_iter47_invalid_code_fix.py --mode run`, valid-range corrected CCC `0.3784`, MAE `7.528`, N `95`.
- **T3 LOSO transportability:** `run_t3_iter47_invalid_code_fix.py --mode loso`, two-way mean CCC `0.150`.

The strongest internal modeling pattern remains:

1. T1: per-item / hybrid item architecture with fold-local feature selection and multi-base tree ensembles.
2. T3: clinical/intake plus IMU residual architecture, not pure IMU deployment.
3. Shared implementation law: subject-level splits, fold-local target/distribution-derived operations, and cache provenance sidecars.

## Decision

No clean, reportable local WearGait-only architecture currently beats the existing architecture under the repository gates.

The better model architecture is therefore **not another local model family**. The defensible next modeling architecture is an **external-data-first, protocol-aware, subject-grouped architecture**:

- train/evaluate across approved external wearable-UPDRS cohorts only after data-owner access and row-level schema inspection;
- keep WearGait-PD as the internal reference cohort, not the sole model-search substrate;
- make external datasets transportability rows first, and only consider augmentation after a separate preregistered screen clears the repository promotion gates;
- preserve the current fold firewall and manifest requirements for every reusable cache;
- group by subject and visit/session where repeated labels exist;
- hard-stop if approved data lack total Part III, full T1 item coverage, or enough feature-readable PD subjects.

## Why Not A New Local Architecture

Fresh verification evidence:

- `results/current_goal_state_verification_20260508.json`: `current_state_verified=true`, `goal_complete=false`.
- `results/remaining_blocker_action_audit_20260509.json`: `passed=true`, `source_blocker_count=36`, `local_model_actions=0`, `unmatched_blockers=0`.
- `results/prompt_objective_evidence_audit_20260508.json`: `goal_complete=false`, `checks=12`, `hard_gaps=1`.
- `./gpu.sh --status`: remote RTX 4060 is idle, no jobs running after the hygiene-corrected iter34 rerun completed.
- T1 iter34 hygiene-corrected rerun: CCC `0.7170`, MAE `1.7356`, N `92`; classified by `audit_t1_iter34_hygiene_corrected.py` as `corrected_candidate_degraded_but_above_0_700`.
- T1 hygiene-corrected residual anatomy: `audit_t1_hygiene_residual_anatomy.py` uses existing OOF artifacts only and reports decision `diagnostic_only_external_data_first_remains`. On the N=92 common cohort, corrected iter34 beats iter12 by CCC `+0.0532`, is below original iter34 by `-0.0153`, has max leave-one |dCCC| `0.0398`, and leaves residual structure concentrated in tail/site/postural-item patterns rather than a fresh local model architecture.

Recent architecture attempts that close obvious local alternatives:

- End-to-end HARNet fine-tuning at N=94 failed: CCC `0.1324`, held-out fold collapse.
- T1 iter46 ET-only robustification did not beat iter34 and did not strictly clear iter12.
- T3 low-degree nested clinical/IMU convex mix failed: CCC `0.3083` vs baseline `0.3759`.
- T3 local-neighbor residual wildcard failed.
- T1 item-13 posture-only axial-orientation screen showed signal but failed the pre-set gate: best 5-fold CCC `0.2059`, delta `+0.046`, seed std `0.0257`, frac>0 `0.705`; no LOOCV promotion.
- T1 2026-05-10 ceiling-push family closed with three 5-fold screen failures under the pre-registered gate (`Delta mean >= +0.025` and paired-bootstrap `frac>0 >= 0.95`):
  - Slot A iter37 phase-locked items 9+12 routed post-K=500: Delta vs iter34 `-0.0021`, frac>0 `0.172`.
  - Slot B iter38 FoG events + balance geometry routed post-K=500: Delta vs iter34 `-0.0002`, frac>0 `0.498`.
  - Slot C iter39 per-item-averaged K=500 selection: Delta vs iter34 `-0.0202`, frac>0 `0.056`, materially different selector (`204/500` mean overlap) but worse.
- Joint-pool feature additions keep reproducing the K=500 absorption / selection-fragility pattern.

The residual/anatomy audits indicate the remaining T3 error is dominated by target observability and cohort/protocol limits rather than an untried small-N estimator:

- corrected T3 residuals are dominated by non-gait / upper-limb / rigidity / tremor burden;
- clinical/intake plus IMU outperforms IMU-only, but pure IMU signal is much lower;
- external zero-shot rows show partial transport only and cannot update internal WearGait-PD headlines.

## Recommended Architecture Boundary

### Keep

- Keep the current internal headline architecture and framing:
  - T1 iter12 as canonical floor.
  - T1 iter34 hygiene-corrected candidate / post-publication replication target.
  - T3 iter47 as corrected valid-range canonical.
- Keep `inductive_lib.py` as the fold-firewall source of truth.
- Keep experiment runners self-contained unless a shared helper is stable and leakage-safe.
- Keep cache manifests mandatory before any cache feeds an inductive headline.

### Do Not Do

- Do not launch another WearGait-only T1/T3 model family from the current feature pool.
- Do not run post-hoc LOOCV for the failed item-13 axial screen.
- Do not expand seeds after seeing a near-positive screen.
- Do not use external zero-shot CCCs as internal headline updates.
- Do not synthesize clean manifests for incomplete historical caches.

### Next Architecture Enabler

The next executable architecture work is gated access, not modeling:

1. Submit PPMI / Verily Study Watch access using `scripts/ppmi_verily_tier3_request_packet.md`.
2. If PPMI is unavailable or pending, submit WATCH-PD using `scripts/watchpd_request_packet.md`.
3. After approval only, run a read-only schema probe and create a new preregistered external-data architecture screen.

Operational bridge after user submission:

- `scripts/record_access_submission.py` records non-protected submission metadata into `.access_submissions/` after the user submits an access request.
- `.access_submissions/` is gitignored, and `audit_access_submission_recorder.py` verifies that the recorder refuses non-ignored output paths by default and fails closed on malformed tracker JSON without a traceback.
- A recorded submission is not approval: the lifecycle becomes `submitted_pending_approval`, the next action is `wait_for_access_approval`, and schema probes/downloads/preregistrations/remote jobs/model runs/canonical updates remain blocked.
- `scripts/record_access_approval.py` records non-protected approval metadata into `.access_approvals/` after data-owner approval.
- `.access_approvals/` is gitignored, and `audit_access_approval_recorder.py` verifies that approval evidence is metadata-only, refuses non-ignored output paths by default, and fails closed on malformed submission/approval input JSON without a traceback.
- A recorded approval unlocks only `run_read_only_schema_probe`; downloads/caches/preregistrations/remote jobs/model runs/canonical updates remain blocked until later gates.
- `scripts/record_schema_probe_report.py` records a scrubbed post-approval `SchemaProbeArtifactEvidence` payload into `.schema_probes/` from manually supplied schema metadata.
- `.schema_probes/` is gitignored, and `audit_schema_probe_recorder.py` verifies that real writes require approval evidence, low-N or incomplete probes fail closed, row dumps/preregistration/model starts are rejected, non-ignored output paths are refused by default, and malformed approval/tracker input JSON fails closed without a traceback.
- A recorded schema-probe artifact can support later preregistration only if the existing schema-probe, artifact-content, execution, and preregistration gates accept it; it still does not authorize download, cache extraction, remote jobs, model runs, or canonical updates.
- `audit_access_lifecycle_state_handoff.py` records the current local access lifecycle as a state-aware handoff without emitting ignored record paths or filenames. It maps today's packet-ready state to `submit_access_request`, and it verifies the submitted/approved transitions to `wait_for_access_approval` and `run_read_only_schema_probe`.

Recorder Input Loader Guard: the submission, approval, and schema-probe recorder scripts now normalize malformed local tracker/submission/approval JSON into short fail-closed command errors instead of Python tracebacks. This keeps corrupted ignored handoff files from bypassing the external access lifecycle or confusing the first approved schema-probe step.

## Bottom Line

The current architecture should not be replaced by another local estimator. The better architecture is a data/protocol architecture: approved external wearable-UPDRS cohorts, subject/visit-grouped validation, strict manifests, and preregistered transport/augmentation gates.

Until that access exists, the correct local action is to preserve the current architecture, report its caveats, and avoid further WearGait-only ceiling fishing.

## Software Architecture Addendum

The codebase architecture has a separate, concrete improvement path. `audit_software_architecture.py` quantifies the current repository shape and writes:

- `results/software_architecture_audit_20260510.json`
- `results/software_architecture_audit_20260510.md`

Fresh audit summary:

- Python files: `395`
- Total Python LOC: `176270`
- Experiment runners: `154` files / `83025` LOC
- Architecture facades: `25` files / `1737` LOC
- Shared core: `7` files / `1157` LOC
- Local import edges: `752`
- Cross-script edges: `305`
- Non-exception cross-script edges: `301`
- Syntax-unreadable files: `0`

Highest fan-in modules:

- `project_paths`: imported by `173` local files
- `inductive_lib`: imported by `123` local files
- `run_t1_iter4`: imported by `61` local files
- `data_split`: imported by `50` local files
- `run_t3_iter2`: imported by `49` local files
- `run_t3_iter5_clinical`: imported by `49` local files
- `run_t3_iter3`: imported by `30` local files
- `run_per_item_v2`: imported by `28` local files

Software decision:

The better codebase architecture is **layered facades without bulk-moving historical scripts**. The flat script ledger is valuable because it preserves provenance for failed, leaky, superseded, and canonical experiments. A mass refactor would be high-risk and low-value. The problem to fix is that new work keeps importing helpers from historical `run_*.py` scripts, turning old experiments into hidden APIs.

Recommended target layout for new work:

- `pd_imu/core`: paths, target construction, split contracts, metrics, cache provenance, fold-local transforms.
- `pd_imu/datasets`: WearGait and external-cohort loaders returning typed subject/visit tables.
- `pd_imu/features`: manifest-backed cache readers/builders with label-use metadata.
- `pd_imu/pipelines`: reusable fold-local `PipelineSpec` objects for T1, T3, and external validation.
- `pd_imu/experiments`: thin CLI wrappers that bind preregistration, run specs, and write artifacts.
- `pd_imu/reporting`: claim ledger, figure generation, manuscript/export validation.

`ArtifactLedger` / `ArtifactRecord` in `pd_imu/core/artifacts.py` now provide the shared filesystem-backed observation layer for these boundaries. Execution and reporting gates can consume a ledger instead of ad hoc observed-path tuples, ledger records can include file size and SHA-256 for existing artifacts, and ledger validation flags blank, duplicate, malformed, missing-record, fake-hash, or unhashable artifact observations.

Artifact Ledger Observation Guard: `ArtifactLedger.from_paths()` now records path observation, stat, and hash failures as validation errors instead of raising while the ledger is being constructed. Unhashable artifacts therefore cannot crash execution/reporting gates or masquerade as clean hashed evidence.

Migration rule:

Do not move old `run_*.py` files in bulk. Add facades first, extract only canonical/future external-data code paths, and block new `run_* -> run_*` imports except explicitly grandfathered historical exceptions. This gives the repo a better architecture without invalidating archaeological evidence.

## Import Boundary Guard

The migration rule is now executable:

- `audit_import_boundaries.py`
- `tests/test_import_boundaries.py`
- `results/import_boundary_baseline_20260510.json`
- `results/import_boundary_audit_20260510.json`
- `results/import_boundary_audit_20260510.md`

The baseline records `301` grandfathered non-exception cross-script import edges. The guard then compares the current repository against that baseline and fails if a new `run_*` / `compose_*` / `cache_*` style cross-script dependency appears outside the allowed exceptions.

Latest run:

- Baseline edge count: `301`
- Current edge count: `301`
- New edges: `0`
- Unauthorized `pd_imu` package-to-legacy imports: `0`
- Decision: `import_boundary_guard_passed`

This does not claim the current architecture is clean. It turns the recommended architecture into an enforceable boundary for future work while preserving the historical experiment ledger. The guard now also makes the package boundary explicit: `pd_imu` may only import historical experiment scripts through `pd_imu/core/legacy_experiment_api.py`; any other `pd_imu -> run_*` / `compose_*` / `cache_*` import fails.

## PipelineSpec Contract

The target `pd_imu/pipelines` layer now has a first contract for future work:

- `pd_imu/pipelines/spec.py`
- `pd_imu/pipelines/__init__.py`
- `tests/test_pipeline_spec.py`
- `audit_pipeline_spec_contract.py`
- `results/pipeline_spec_contract_audit_20260510.json`
- `results/pipeline_spec_contract_audit_20260510.md`

`PipelineSpec` records:

- dataset/cohort identity, subject/visit grouping keys, external route id, protected-access status, and minimum-N hard stops;
- target type, source columns, valid range, and missingness policy;
- feature blocks with manifest, label-use, and fold-scope policy;
- validation strategy, group key, splits, seeds, and site key;
- promotion/null-gate thresholds;
- required output artifacts such as preregistration, OOF predictions, manifests, and row predictions.

The contract now fails closed on blank component identities, malformed field types, duplicate grouping keys, duplicate feature block names, blank feature declarations, and label-using feature blocks before preregistration hashes or experiment specs are accepted. Dataset grouping keys, target source columns/ranges, validation split/seeds/site fields, gate thresholds/null gates, artifact booleans, feature block booleans/notes, top-level notes, and metadata are all explicitly validated rather than relying on dataclass type hints.

This is deliberately a contract layer, not a modeling abstraction. It gives future external-data screens a typed, hashable spec without importing from historical experiment scripts.

## Dataset And Feature Contracts

The target `pd_imu/datasets` and `pd_imu/features` layers now have first contracts:

- `pd_imu/datasets/schema.py`
- `pd_imu/datasets/probe.py`
- `pd_imu/datasets/__init__.py`
- `pd_imu/features/spec.py`
- `pd_imu/features/__init__.py`
- `tests/test_dataset_feature_specs.py`
- `audit_dataset_feature_contract.py`
- `results/dataset_feature_contract_audit_20260510.json`
- `results/dataset_feature_contract_audit_20260510.md`

`SubjectTableSpec` / `CohortSchema` / `DatasetReadiness` make access-gated external-data rules explicit: required subject/visit columns, target columns, sensor modalities, minimum valid-subject hard stops, protected-access status, and row-level schema inspection. They now reject malformed runtime field types such as string-valued column collections, non-boolean access flags, non-integer subject counts, or non-`CohortSchema` readiness inputs before any external route can preregister.

`SchemaProbeSpec` / `SchemaProbeReport` define the first code artifact allowed after external access approval: a read-only probe that inventories files, subject/visit linkage, sensor metadata, targets, missingness policy, grouping policy, and hard stops. It can unlock preregistration only after access approval, complete schema sections, required grouping keys, target fields, sensor modalities, minimum N, and no protected row dumps or premature modeling. The schema-probe contract now covers all six packet-ready external routes: PPMI/Verily, PPP/PD-VME, WATCH-PD, CNS Portugal/Lobo, Hssayeni/MJFF, and ICICLE-GAIT.

`SchemaProbeReport` also fails closed on ambiguous observed schema inventories: blank or duplicate observed sections, grouping keys, target columns, and sensor modalities are rejected before a probe can support preregistration.

`SchemaProbeArtifactEvidence` validates the written probe artifact content against the in-memory `SchemaProbeReport` before protected preregistration or run stages proceed. A stale route id, changed valid-subject count, mismatched required fields, malformed field type, protected row dump, premature modeling flag, row-like payload key, or credential-like payload key now blocks the execution gate even if the schema-probe path exists.

`FeatureMatrixSpec` / `FeaturePolicy` make feature-block rules explicit: join key, required columns, manifest requirement, label-use prohibition, allowed fold scopes, and headline-safe manifest enforcement. They now reject malformed runtime field types such as non-string identities, non-list required columns, non-boolean manifest/label flags, malformed fold-scope collections, and non-`FeaturePolicy` policy objects.

`FeatureManifestArtifactEvidence` validates a written feature-cache manifest against a pipeline feature block before a completed result bundle can support downstream claims. It checks the feature name, cache path, sidecar path, required manifest fields, nullish placeholders, typed manifest fields, cache hash, label-use policy, fold scope, headline-safe leakage status, missing or invalid manifest source JSON, and absence of row-like or credential-like payload keys.

These contracts now fail closed on blank, duplicate, or malformed field-type schema, probe, and feature identifiers while still accepting clean manifest-backed feature matrices.

These contracts support the external-data-first architecture without adding loaders, model code, or any new result claim.

## Experiment And Reporting Contracts

The remaining target layers now have first contracts:

- `pd_imu/experiments/spec.py`
- `pd_imu/experiments/execution.py`
- `pd_imu/experiments/__init__.py`
- `pd_imu/reporting/claims.py`
- `pd_imu/reporting/current_truth.py`
- `pd_imu/reporting/__init__.py`
- `tests/test_experiment_reporting_specs.py`

`ExperimentSpec` binds a validated `PipelineSpec` to a concrete command, preregistration record, formula hash, and required artifacts. It checks that the preregistration hash matches the pipeline, that command tokens and owner fields are well formed, that artifact declarations have string kind/path values, that singleton artifact kinds are not duplicated, and that required outputs such as preregistration, OOF predictions, manifests, row predictions, and schema-probe artifacts are declared before a runner executes.

For protected external routes, `ExternalExperimentReadiness` now connects the schema-probe contract directly to future experiment specs. If `PipelineSpec.dataset.protected_access_required` is true, the experiment cannot validate without a matching route id, a clean `SchemaProbeReport`, a sufficient valid-subject count, and a required `schema_probe` artifact path matching the probe report. This prevents a preregistration or run command from being considered valid merely because access was approved.

`AccessApprovalEvidence` separates protected-data approval proof from route-state booleans. A route marked `approved_access=True` is no longer enough to start a protected schema probe: the execution gate also needs non-protected approval metadata with matching route id, approval source, approval timestamp, accepted data-use terms, a documented protected-data storage plan, and no protected row dump, credentials, or tokens.

`AccessSubmissionEvidence` covers the step between submit-ready packet and approval. It can record non-protected submission metadata for a route, but it rejects completed packets/signatures, credentials/tokens, protected row dumps, and any claim that submission equals approval. Submission evidence deliberately cannot unlock schema probes or model work.

`AccessRouteLifecycle` ties the packet, submission, and approval evidence into one fail-closed state machine. `packet_ready` and `submitted_pending_approval` keep every pre-access compute action blocked; `approved_for_schema_probe` unlocks only read-only schema probing and keeps downloads, cache extraction, preregistration, remote jobs, model runs, and canonical updates blocked until later gates pass.

`AccessNextAction` converts that lifecycle state into one safe operational decision for future tooling: submit the access request, wait for approval, run only the read-only schema probe, or fix invalid evidence. It carries the allowed action, the still-blocked actions, and whether code execution is safe, so callers do not reimplement route-state branching.

`ExperimentExecutionGate` adds the execution-stage layer that future runners should call before doing work. It treats access request, schema probe, preregistration, and run as executable stages. Protected external schema probes require explicit `AccessApprovalEvidence` or an approved `AccessRouteLifecycle`; submitted-only lifecycles still fail closed. Protected external preregistration requires approved lifecycle/approval evidence plus observed and content-validated schema-probe evidence; protected external runs require approved lifecycle/approval evidence, observed and content-validated schema-probe evidence, and observed preregistration artifact. Canonical-claim updates are deliberately not authorized by this execution gate; they must go through `CanonicalClaimUpdateGate`, which binds the complete result bundle, reporting evidence, and metric-to-OOF evidence.

`PreregistrationArtifactEvidence` adds content validation for the run stage. A future run is no longer allowed merely because a preregistration path exists; the parsed preregistration artifact must be declared by the experiment, must match the experiment's pipeline name, formula hash, timestamp, and git SHA when provided, must use typed scalar/list fields, and must not carry row-like or credential-like payload keys.

`ExperimentResultBundle` represents the next boundary after a run completes: an `ExperimentSpec`, a filesystem-backed `ArtifactLedger`, matching preregistration evidence, feature manifest content evidence, and parsed OOF/row prediction artifact evidence. It validates that every required result artifact is observed, every manifest-required feature block has matching clean manifest evidence, every manifest evidence payload has typed fields and no row-like or credential-like extras, and required prediction artifacts have readable CSV sources, expected columns, pipeline grouping keys, nonblank grouping values, unique group counts, matching OOF/row group fingerprints, finite numeric values, valid OOF targets, valid fold ids, expected fold coverage, and minimum row counts before downstream claim-update or reporting layers treat the run as complete.

`ClaimSpec` / `ReportingSurfaceSpec` encode the claim-label discipline that the project now relies on: canonical, candidate, historical, retracted, external-transport, and diagnostic claims have different requirements, claim names must be unique inside a reporting surface, and external-transport or retracted claims cannot update internal canonicals.

`ReportingEvidenceGate` binds those claim labels to observed artifacts before a surface is allowed to emit text. A reporting surface now has to pass label/framing validation, unique-claim-name validation, unique metric-evidence-name validation, required-snippet validation, source-artifact presence checks, metric-content checks, true hex SHA-256 metric-evidence hash checks, scrubbed claim metric payload checks, and source-artifact hash checks together when a hashed `ArtifactLedger` is provided. `ClaimMetricEvidence` provides the JSON-path binding from a claim to the source artifact fields that carry its metric value and N, and file-backed metric evidence carries the parsed artifact SHA-256.

`CanonicalClaimUpdateGate` closes the last claim-update boundary: an internal canonical update now needs a complete `ExperimentResultBundle`, a passing `ReportingEvidenceGate`, and an updating canonical claim whose source artifact belongs to that bundle. When the claim source is a metrics artifact, it also needs `MetricArtifactEvidence` that recomputes the metric JSON from the required OOF predictions. Protected external result bundles remain blocked from internal canonical updates.

`CurrentResultClaim` / `current_weargait_result_claims()` centralize the current internal WearGait-PD truth table for new reporting code. The registry binds the T1 canonical floor, T1 strongest candidate, T3 corrected valid-range canonical, and T3 LOSO transportability rows to their source artifacts, commands, preregistration files, required supporting artifacts, JSON metric paths, and hashed source-artifact observations before `ReportingEvidenceGate` consumes them. It now also validates command tokens, metric/N paths, supporting artifact references, notes, and duplicate artifact references before those bindings are accepted.

This completes the first-pass target package skeleton for new work:

- `pd_imu/core`
- `pd_imu/datasets`
- `pd_imu/features`
- `pd_imu/pipelines`
- `pd_imu/experiments`
- `pd_imu/reporting`

The scope remains deliberately limited. These modules are contracts and facades for future architecture work, not a mass refactor of historical scripts and not a new model result.

## External Architecture Route Plan

The model-side hard gap is now represented as an explicit route-readiness contract:

- `pd_imu/experiments/routes.py`
- `audit_external_route_access_contract.py`
- `audit_external_architecture_route_plan.py`
- `results/external_route_access_contract_audit_20260510.json`
- `results/external_route_access_contract_audit_20260510.md`
- `results/external_architecture_route_plan_20260510.json`
- `results/external_architecture_route_plan_20260510.md`

Latest decision:

- Access-request routes: `6`
- Compute-ready routes: `0`
- Top priority route: `PPMI / Verily Study Watch`
- Decision: `external_architecture_routes_blocked_until_access`

This converts the remaining model-architecture blocker into an auditable plan: no probe, cache extraction, pre-registration, remote job, model run, or canonical claim update is allowed before access approval and row-level schema inspection.

The route/access contract now rejects malformed route field types, duplicate route ids, unknown route action states, blank access blockers, and duplicate or unknown blocked pre-access actions while the real tracker-derived queue remains compute-blocked and unambiguous.

## External Access Packet Integrity

The access-gated architecture path now has a consolidated freshness guard:

- `pd_imu/experiments/access.py`
- `audit_external_access_packet_integrity.py`
- `results/external_access_packet_integrity_audit_20260510.json`
- `results/external_access_packet_integrity_audit_20260510.md`

Latest decision:

- Submit-ready routes: `6`
- Compute-ready routes: `0`
- Top priority route: `PPMI / Verily Study Watch`
- Decision: `external_access_packets_integrity_passed_no_compute`

This audit reruns the six route-specific request-packet audits, the external access-readiness audit, the submission tracker, and the route-plan audit. It verifies that packets remain ready to fill and submit after user-side governance details are added, while protected-data probes, downloads, cache extraction, preregistrations using new labels, remote jobs, model runs, and canonical claim updates remain blocked.

`AccessPacketSpec` and `AccessPacketQueue` now make that state reusable by future runners and audits: a route can be submit-ready only when the packet and runbook are ready, user-fill placeholders remain, all pre-access compute actions are blocked, and neither remote jobs nor scaffolds are marked allowed. Malformed runtime field types such as string booleans, non-integer priorities, non-list blocked actions, or non-packet queue entries now fail as validation errors instead of being treated as truthy state.

## External Approval Evidence Gate

The first post-approval action now has an evidence gate before any protected-data schema probe:

- `pd_imu/experiments/access.py`
- `audit_external_approval_evidence_gate.py`
- `results/external_approval_evidence_gate_audit_20260510.json`
- `results/external_approval_evidence_gate_audit_20260510.md`

Latest decision:

- Decision: `external_approval_evidence_gate_passed`
- Hard failures: `0`

`AccessApprovalEvidence` means a route-state boolean is no longer enough to unlock protected-data probing. The evidence must name the route, approval source, approval timestamp, accepted data-use terms, and protected-data storage plan, and it must not contain protected rows, credentials, or tokens. Malformed approval field types fail closed. `ExperimentExecutionGate` now requires this evidence for protected schema probes and keeps requiring it for protected preregistration/run stages.

## External Submission Evidence Gate

Submitted access requests now have a non-protected evidence contract:

- `pd_imu/experiments/access.py`
- `audit_external_submission_evidence_gate.py`
- `results/external_submission_evidence_gate_audit_20260510.json`
- `results/external_submission_evidence_gate_audit_20260510.md`

Latest decision:

- Decision: `external_submission_evidence_gate_passed`
- Hard failures: `0`

This covers the gap after a packet is submit-ready but before data-owner approval exists. A submitted packet can be recorded without committing completed forms, signatures, credentials, or protected rows, and the evidence cannot unlock schema probes or model work. Malformed submission field types fail closed. `AccessApprovalEvidence` remains the only post-approval object that can let a protected schema probe start.

## External Access Lifecycle Gate

External route state now has a small fail-closed lifecycle contract:

- `pd_imu/experiments/access.py`
- `audit_external_access_lifecycle_gate.py`
- `results/external_access_lifecycle_gate_audit_20260510.json`
- `results/external_access_lifecycle_gate_audit_20260510.md`

Latest decision:

- Decision: `external_access_lifecycle_gate_passed`
- Hard failures: `0`

This closes the gap between separate packet, submission, and approval evidence objects. Packet-ready and submitted-pending-approval routes remain fully pre-access blocked. Approval evidence moves the route only to `approved_for_schema_probe`, which permits a read-only schema probe while keeping downloads, caches, preregistration, remote jobs, model runs, and internal canonical updates blocked. Malformed lifecycle field types fail closed before they can unlock a state transition.

## External Next-Action Gate

External route lifecycles now produce one safe next-action object:

- `pd_imu/experiments/access.py`
- `audit_external_next_action_gate.py`
- `results/external_next_action_gate_audit_20260510.json`
- `results/external_next_action_gate_audit_20260510.md`

Latest decision:

- Decision: `external_next_action_gate_passed`
- Hard failures: `0`

This keeps future scripts and dashboards from duplicating access-state branching. A packet-ready route allows only access submission, a submitted route waits for approval, an approved route allows only read-only schema probing, and invalid evidence allows only evidence repair. Malformed next-action field types fail closed. Modeling, cache extraction, preregistration, remote jobs, and canonical updates remain blocked until later gates.

## Access Lifecycle State Handoff

The operational handoff for the active PPMI/Verily route is now state-aware:

- `audit_access_lifecycle_state_handoff.py`
- `results/access_lifecycle_state_handoff_20260515.json`
- `results/access_lifecycle_state_handoff_20260515.md`

Latest decision:

- Decision: `access_lifecycle_state_handoff_ready`
- Current action: `submit_access_request`
- Record identities redacted: `true`
- Record paths reported: `false`

This complements the stricter zero-record handoff. After a metadata-only submission record exists, the state-aware handoff reports `wait_for_access_approval`; after metadata-only approval exists, it reports `run_read_only_schema_probe`. It does not authorize protected downloads, cache extraction, preregistration, remote jobs, model runs, or canonical updates.

## Current External Route Sweep

A fresh route sweep after the architecture result-bundle work is recorded in:

- `audit_current_external_route_sweep.py`
- `results/current_external_route_sweep_20260510.json`
- `results/current_external_route_sweep_20260510.md`

Latest decision:

- Decision: `current_external_route_sweep_documented_no_compute_route`
- Routes checked: `3`
- New compute-ready routes: `0`
- New access-packet actions: `0`
- New scaffold/preregistration actions: `0`

The only newly ledgered route is ProPark / Hepp 2025: a request-gated, wrist AX6, tremor-focused home-monitoring cohort with MDS-UPDRS Part III context. It is not added to the six-route access packet queue because schema, raw-file structure, usable total-score linkage, and data-use terms are uninspected, and the published endpoint is tremor items 15-18 rather than WearGait-style gait/balance severity. The sweep also confirms that the 2026 Gait & Posture DeFoG analysis is an alias of the already-tested TLVMC/DeFOG route, and that COPS remains the already-closed iter49 external-validity row.

## External Schema Probe Contract

The post-approval step is now represented as a reusable dataset contract and verifier:

- `pd_imu/datasets/probe.py`
- `audit_external_schema_probe_contract.py`
- `results/external_schema_probe_contract_audit_20260510.json`
- `results/external_schema_probe_contract_audit_20260510.md`

Latest decision:

- Decision: `external_schema_probe_contract_passed`
- Hard failures: `0`

This closes the gap between "access approved" and "model run allowed": after approval, only a read-only schema probe is valid. The probe must not include protected row dumps, write a preregistration, or start a model run. It can only unlock preregistration after the route has confirmed subject/visit grouping, target columns, sensor modalities, valid-subject count, missing-code policy, and hard-stop conditions. The latest verifier covers all six packet-ready external routes and checks that protected external `ExperimentSpec` objects reject missing or contaminated probes and accept only a clean probe artifact bound to the experiment.

## Schema Probe Artifact Gate

The schema-probe path is now content-validated before it can unlock protected preregistration or run stages:

- `pd_imu/datasets/probe.py`
- `audit_schema_probe_artifact_gate.py`
- `results/schema_probe_artifact_gate_audit_20260510.json`
- `results/schema_probe_artifact_gate_audit_20260510.md`

Latest decision:

- Decision: `schema_probe_artifact_gate_passed`
- Hard failures: `0`

`SchemaProbeArtifactEvidence` is the schema-probe analogue of preregistration content evidence. It checks that the artifact payload matches the expected route id, route name, required grouping keys, target columns, sensor modalities, required sections, approved-access state, valid-subject count, contamination flags, and artifact path. An observed schema-probe path alone can no longer unlock protected modeling when the file content is stale, mismatched, malformed, missing or invalid at load time, contaminated, or contains row-like or credential-like payload keys.

Schema Probe Redaction Guard: schema-probe artifacts now scan their JSON payload recursively for explicit row-like, label/value, prediction, and credential/token keys. This keeps aggregate schema metadata available while preventing a probe artifact from smuggling protected rows or secrets behind a clean boolean flag.

Schema Probe Artifact Type Guard: schema-probe artifacts now fail closed when list-valued fields arrive as strings, integer thresholds arrive as text, boolean flags arrive as truthy strings, or the payload/spec object is not a JSON object. This prevents malformed external probe artifacts from passing by implicit Python coercion or by crashing the validator outside the audit path.

Schema Probe Artifact Loader Guard: `SchemaProbeArtifactEvidence.from_file()` now converts missing or malformed source JSON into validation errors instead of raising before `ExperimentExecutionGate` can evaluate protected preregistration or run readiness. This keeps stale or absent schema-probe files on the same fail-closed path as mismatched route metadata, row-dump flags, and hidden protected payload keys.

## Experiment Execution Gate

The future-runner boundary is now represented as an execution-stage verifier:

- `pd_imu/experiments/execution.py`
- `audit_experiment_execution_gate.py`
- `results/experiment_execution_gate_audit_20260510.json`
- `results/experiment_execution_gate_audit_20260510.md`

Latest decision:

- Decision: `experiment_execution_gate_passed`
- Hard failures: `0`

This prevents the architecture from relying only on declarations. A future protected external runner must pass the stage gate before it can preregister or run: pre-access state allows only access-request work; schema probes require approved access and cannot bind an experiment; preregistration requires a clean observed schema-probe artifact; runs require the preregistration artifact to already exist; protected external experiments remain blocked from internal canonical-claim updates. Internal canonical updates are also not executable from `ExperimentExecutionGate`; callers must use `CanonicalClaimUpdateGate`.

The execution audit now consumes `AccessRouteLifecycle`: submitted-pending-approval lifecycle evidence is rejected for schema probing, while approved lifecycle evidence can unlock the read-only schema-probe stage and can serve as approval proof for protected preregistration once schema-probe artifacts exist.

Execution Gate Nested Evidence Guard: malformed top-level route, experiment, access-approval evidence, access-lifecycle, schema-probe evidence, preregistration evidence, artifact-ledger, or observed-path inputs now fail closed as validation errors. The gate skips invalid objects when computing observed or required artifacts, so malformed execution state cannot crash the validator or accidentally satisfy a protected preregistration/run prerequisite.

## Preregistration Artifact Gate

The run-stage gate now validates preregistration file contents:

- `pd_imu/experiments/preregistration.py`
- `audit_preregistration_artifact_gate.py`
- `results/preregistration_artifact_gate_audit_20260510.json`
- `results/preregistration_artifact_gate_audit_20260510.md`

Latest decision:

- Decision: `preregistration_artifact_gate_passed`
- Hard failures: `0`

This closes the gap between "the preregistration file exists" and "the preregistration file belongs to this exact experiment." The audit writes a controlled preregistration artifact, validates it against an `ExperimentSpec`, rejects stale formula hashes and undeclared preregistration paths, rejects malformed scalar/list fields, rejects missing or invalid source JSON, rejects row-like and credential-like payload keys, and confirms that `ExperimentExecutionGate(stage="run")` requires content evidence.

Preregistration Artifact Loader Guard: `PreregistrationArtifactEvidence.from_file()` now converts missing or malformed source JSON into validation errors instead of raising before `ExperimentExecutionGate(stage="run")` can validate preregistration content evidence. This keeps absent or corrupted preregistration files on the same fail-closed path as stale formula hashes and contaminated payloads.

## Experiment Result Bundle

Completed runs now have a reusable result-bundle contract:

- `pd_imu/experiments/results.py`
- `audit_experiment_result_bundle.py`
- `results/experiment_result_bundle_audit_20260510.json`
- `results/experiment_result_bundle_audit_20260510.md`

Latest decision:

- Decision: `experiment_result_bundle_passed`
- Hard failures: `0`

This closes the boundary between "a command finished" and "the run can support claims." The bundle audit creates controlled preregistration, OOF, manifest, feature cache, row-prediction, metrics, and visit-level prediction artifacts, then verifies complete bundles, missing required outputs, stale preregistration evidence, feature manifest content evidence, malformed or protected feature-manifest payload rejection, missing or invalid feature-manifest source JSON rejection, parsed prediction artifact evidence, metric artifact evidence, grouping-key-aware prediction evidence, prediction CSV source-loader failures, nonblank prediction identity values, non-ragged CSV rows, OOF/row group-set consistency, metric-to-OOF recomputation consistency, malformed metric JSON path rejection including empty path segments, malformed or protected metric-payload rejection, missing/malformed metric JSON source rejection, missing/unreadable/malformed OOF source rejection for metric recomputation, numeric prediction/target validation, OOF fold coverage validation, hashed artifact ledgers, hex digest validation, malformed command/owner/artifact metadata rejection, malformed nested experiment contract object rejection, malformed result-bundle evidence object rejection, blank artifact declaration rejection, and duplicate singleton artifact-kind rejection. Missing, stale, hash-mismatched, label-using, wrong-fold-scope, malformed, missing/invalid-source, row-like, or credential-like feature manifests keep the bundle incomplete; missing, stale, OOF-mismatched, hash-mismatched, malformed-path, missing/invalid-metric-json-source, missing/unreadable/malformed-OOF-source, malformed-payload, row-like, credential-like, or undeclared metric artifacts keep the bundle incomplete; malformed experiment commands/owners/artifact declarations or malformed nested pipeline/preregistration/readiness/artifact objects keep the spec invalid; malformed artifact ledgers, malformed preregistration evidence, malformed feature/prediction/metric evidence collections, missing, unreadable, malformed, ragged-row, grouping-key-mismatched, blank-identity, group-set-mismatched, duplicate-OOF, invalid-fold, incomplete-fold-coverage, nonnumeric, nonfinite, out-of-target-range, non-hex-digest, or too-short prediction artifacts also keep the bundle incomplete.

Feature Manifest Loader Guard: `FeatureManifestArtifactEvidence.from_cache_path()` now converts missing or malformed manifest source JSON into validation errors instead of raising before `ExperimentResultBundle` can evaluate completed-run readiness. This keeps absent or corrupted feature sidecars on the same fail-closed path as hash mismatches, label-use violations, wrong fold scopes, and protected payload keys.

`MetricArtifactEvidence` is the metric-output analogue of prediction evidence. It parses a metrics JSON artifact, recomputes metrics from the required OOF prediction artifact, and rejects a result bundle when the reported metric values do not match the OOF predictions they claim to summarize. This closes the gap between "the metric JSON validates as a claim source" and "the metric JSON belongs to this run's predictions."

Metric OOF Source Guard: `MetricArtifactEvidence.from_json_and_oof_csv()` now records missing, unreadable, or malformed OOF recomputation errors as validation failures instead of raising before bundle validation can run. Missing files, malformed path/root inputs, non-UTF-8 files, empty files, and nonnumeric or nonfinite `y_true`/`y_pred` sources therefore fail closed at the result-bundle boundary.

Metric Artifact Loader Guard: `MetricArtifactEvidence.from_json_and_oof_csv()` now converts missing or malformed metrics JSON into validation errors instead of raising before `ExperimentResultBundle` can evaluate completed-run readiness. Missing and invalid metric JSON sources now fail closed alongside metric/OOF mismatches, malformed metric paths, and protected payload keys.

Metric Artifact Payload Guard: `MetricArtifactEvidence` now also rejects non-object metrics payloads, malformed metric path maps, nonnumeric metric values, and row-like or credential-like metric payload keys. This keeps a future metrics JSON from doubling as a protected row dump or secret-bearing artifact while still matching OOF-recomputed summary values.

`PredictionArtifactEvidence` is the prediction-output analogue of preregistration and feature-manifest evidence. It parses required OOF and row-prediction CSV artifacts, checks expected columns, pipeline grouping keys, nonblank grouping values, row-width consistency, unique group counts, group-set fingerprints, duplicate grouping rows, finite numeric predictions, finite OOF targets, OOF target valid ranges, OOF fold ids, OOF fold coverage against `PipelineSpec.validation.n_splits`, row counts, and true SHA-256 hex digests, and can compare parsed file hashes against a hashed `ArtifactLedger`. Group-set fingerprints allow the bundle to compare OOF and row-prediction cohorts without carrying raw identity lists forward.

Prediction Artifact Loader Guard: `PredictionArtifactEvidence.from_csv()` now converts missing, unreadable, or non-UTF-8 prediction CSV sources into validation errors instead of raising before `ExperimentResultBundle` can evaluate completed-run readiness. This keeps absent or corrupted OOF/row prediction files on the same fail-closed path as missing columns, ragged rows, nonnumeric predictions, invalid fold ids, and group-set mismatches.

## Canonical Claim Update Gate

Internal canonical updates now have a result-backed claim gate:

- `pd_imu/reporting/claims.py`
- `audit_canonical_claim_update_gate.py`
- `results/canonical_claim_update_gate_audit_20260510.json`
- `results/canonical_claim_update_gate_audit_20260510.md`

Latest decision:

- Decision: `canonical_claim_update_gate_passed`
- Hard failures: `0`

This prevents a future runner from treating "required files exist" or "claim text validates" as sufficient for a canonical update. The gate requires the result bundle, the reporting evidence, the updating claim label, and the claim source artifact to agree. If the canonical claim source is a metrics JSON artifact, `MetricArtifactEvidence` must also bind that JSON to metrics recomputed from the run's required OOF predictions. Protected external bundles cannot update internal WearGait-PD canonicals.

Reporting/Canonical Nested Evidence Guard: `ReportingEvidenceGate` now rejects malformed reporting surfaces, observed-path collections, artifact ledgers, claim-metric evidence collections, malformed nested `ClaimSpec` objects, and non-string rendered text before emitting claim text. `CanonicalClaimUpdateGate` now rejects malformed result bundles, malformed reporting gates, and non-boolean update policy flags before it inspects bundle artifacts or reporting claims.

## Reporting Evidence Gate

The reporting layer now has a source-artifact gate:

- `pd_imu/reporting/claims.py`
- `audit_reporting_evidence_gate.py`
- `results/reporting_evidence_gate_audit_20260510.json`
- `results/reporting_evidence_gate_audit_20260510.md`

Latest decision:

- Decision: `reporting_evidence_gate_passed`
- Hard failures: `0`

This prevents claim text from being emitted from labels alone. The audit now sources internal T1/T3 claims from `current_weargait_result_claims()`, adds COPS as an external-transport row, and uses real local evidence artifacts for all rows. It verifies that missing source artifacts, missing required framing snippets, stale metric values, missing metric-evidence hashes for hashed source artifacts, duplicate claim names, duplicate metric-evidence names, non-hex metric-evidence hashes, malformed or protected claim metric payloads, missing or malformed source JSON loaded by `ClaimMetricEvidence.from_json_file()`, or metric evidence for unknown claims block emission.

Reporting Metric Hash Format Guard: `ClaimMetricEvidence` now rejects non-hex 64-character digest strings before a reporting surface can emit a claim. This closes the gap where a fabricated digest such as `"z" * 64` could satisfy a length-only check when no hashed ledger comparison was available.

Metric JSON Path Guard: metric evidence in both completed result bundles and reporting surfaces now rejects malformed JSON path syntax, including nonnumeric bracket indexes and empty path segments such as `metrics..ccc`. This keeps malformed metric path declarations as validation errors instead of uncaught exceptions or silently normalized paths during claim emission or canonical-update checks.

Claim Metric Payload Guard: `ClaimMetricEvidence` now rejects non-object payloads, nonnumeric metric/N values, malformed metric/N path fields, and row-like or credential-like payload keys before a reporting surface can emit a claim. This keeps source evidence for claim text from carrying protected rows or secrets even when the visible metric value and N match.

Claim Metric Evidence Loader Guard: `ClaimMetricEvidence.from_json_file()` now converts missing or malformed source JSON into validation errors instead of raising before `ReportingEvidenceGate` can run. This keeps source-artifact read failures on the same fail-closed reporting path as stale metrics, missing snippets, and bad claim labels.

Reporting/Canonical Nested Evidence Guard: malformed reporting surface/gate objects and malformed canonical update gate objects now fail closed as ordinary validation errors. This keeps future paper/reporting code from crashing or accidentally authorizing a canonical update when a caller passes plain objects, malformed claim collections, malformed observed paths, malformed ledgers, or malformed metric-evidence collections.

## Current Truth Registry

The reporting layer now has a typed registry for current internal WearGait-PD truth:

- `pd_imu/reporting/current_truth.py`
- `audit_current_truth_registry.py`
- `results/current_truth_registry_audit_20260510.json`
- `results/current_truth_registry_audit_20260510.md`

Latest decision:

- Decision: `current_truth_registry_passed`
- Hard failures: `0`

This prevents future reporting code from re-hardcoding the current headline/candidate rows in each audit or surface. The registry audit verifies the expected T1/T3 entries, preserves canonical vs candidate labels, checks all source/preregistration/support artifacts exist, validates source JSON metric paths against the claim values and N, rejects malformed command/path/artifact metadata, and confirms the entries match the current `CLAUDE.md` truth table.

Current Truth Registry Metadata Guard: `CurrentResultClaim` now validates that registry commands are non-empty string token lists, metric/N paths are non-empty strings, preregistration and supporting artifact references are non-empty strings, notes are strings, and duplicate artifact references are rejected. This keeps the central truth registry from silently deduplicating malformed or ambiguous support metadata before reporting gates consume it.

Current Truth Registry Nested Claim Guard: `CurrentResultClaim` now rejects non-`ClaimSpec` claim objects and malformed claim scalar fields before registry helpers dereference claim names or source artifacts. Invalid claim objects no longer crash `artifact_paths()` or silently enter reporting-gate construction; they fail as registry validation errors.

Current Truth Registry Observation Guard: `CurrentResultClaim.validation_errors()` now rejects malformed registry roots and catches artifact path observation failures before checking source/preregistration/support artifact existence. A bad validation root or unobservable artifact path therefore fails closed as a registry validation error instead of raising before reporting gates can inspect the current truth table.

## Artifact Ledger Contract

The gate layers now share a filesystem-backed artifact observation contract:

- `pd_imu/core/artifacts.py`
- `audit_artifact_ledger_contract.py`
- `results/artifact_ledger_contract_audit_20260510.json`
- `results/artifact_ledger_contract_audit_20260510.md`

Latest decision:

- Decision: `artifact_ledger_contract_passed`
- Hard failures: `0`

The audit verifies that the ledger observes existing artifacts, reports missing paths, records SHA-256 hashes when requested, rejects malformed record fields and fake hashes, and can feed both `ExperimentExecutionGate` and `ReportingEvidenceGate`. This removes another ad hoc boundary where future callers could pass hand-assembled path tuples instead of a filesystem-backed artifact snapshot.

## Completion Audit

`audit_architecture_completion.py` writes:

- `results/architecture_completion_audit_20260510.json`
- `results/architecture_completion_audit_20260510.md`

Latest decision:

- Software architecture deliverable complete: `true`
- Model ceiling break complete: `false`
- Overall goal complete: `false`
- Hard gaps: `1`

The remaining hard gap is not a missing software layer. It is the broader model-side criterion: no clean reportable T1/T3 architecture has beaten the current canonicals/candidates under the repository gates.
