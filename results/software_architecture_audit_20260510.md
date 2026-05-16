# Software Architecture Audit - 2026-05-10

This audit quantifies the repository architecture without changing experiment code.

- Decision: `recommend_layered_facade_no_mass_move`
- Python files: `593`
- Total Python LOC: `256857`
- Local import edges: `1089`
- Cross-script edges: `405`
- Non-exception cross-script edges: `401`
- Syntax-unreadable files: `0`

## Category Counts

- `ad_hoc_test_script`: 2 files, 530 LOC
- `architecture_facade`: 26 files, 5033 LOC
- `audit_verifier`: 127 files, 59244 LOC
- `cache_builder`: 39 files, 13818 LOC
- `canonical_pipeline`: 6 files, 2773 LOC
- `composer`: 10 files, 4061 LOC
- `experiment_runner`: 263 files, 111895 LOC
- `legacy_src_module`: 8 files, 1927 LOC
- `miscellaneous`: 27 files, 5832 LOC
- `paper_reporting`: 25 files, 32381 LOC
- `shared_core`: 7 files, 1157 LOC
- `support_script`: 34 files, 11489 LOC
- `tests`: 19 files, 6717 LOC

## Shared Core

- `cache_provenance.py`: 166 LOC
- `data_split.py`: 296 LOC
- `eval_utils.py`: 135 LOC
- `inductive_lib.py`: 245 LOC
- `lgb_ccc_objective_v2.py`: 110 LOC
- `project_paths.py`: 89 LOC
- `updrs_columns.py`: 116 LOC

## Canonical Pipelines

- `compose_t1_iter12_honest.py`: 264 LOC
- `run_t1_iter34_hybrid_8item_multibase.py`: 615 LOC
- `run_t3_iter16_site_ipw.py`: 533 LOC
- `run_t3_iter41_target_fix.py`: 514 LOC
- `run_t3_iter47_invalid_code_fix.py`: 445 LOC
- `run_t3_iter5_clinical.py`: 402 LOC

## Highest Fan-In Local Modules

- `inductive_lib`: imported by 221 local files
- `project_paths`: imported by 206 local files
- `eval_utils`: imported by 110 local files
- `run_t3_iter5_clinical`: imported by 69 local files
- `run_t1_iter4`: imported by 65 local files
- `run_t3_iter2`: imported by 63 local files
- `data_split`: imported by 50 local files
- `run_t3_iter47_invalid_code_fix`: imported by 45 local files
- `run_t3_iter3`: imported by 31 local files
- `run_t1_iter33b_8item_chain`: imported by 29 local files
- `run_per_item_v2`: imported by 28 local files
- `updrs_columns`: imported by 23 local files
- `run_t3_iter41_target_fix`: imported by 13 local files
- `run_t1_iter34_hybrid_8item_multibase`: imported by 13 local files
- `run_ablation_v2`: imported by 12 local files

## Largest Files

- `verify_current_goal_state.py`: 5704 LOC (`audit_verifier`)
- `generate_paper_v4.py`: 5161 LOC (`paper_reporting`)
- `generate_paper_v3.py`: 4949 LOC (`paper_reporting`)
- `generate_paper_v2.py`: 4925 LOC (`paper_reporting`)
- `generate_paper.py`: 4422 LOC (`paper_reporting`)
- `tests/test_experiment_reporting_specs.py`: 3445 LOC (`tests`)
- `audit_proresults_prompt_to_artifact.py`: 3427 LOC (`audit_verifier`)
- `audit_prompt_objective_evidence.py`: 3272 LOC (`audit_verifier`)
- `generate_paper_v6.py`: 2447 LOC (`paper_reporting`)
- `generate_paper_v5.py`: 2339 LOC (`paper_reporting`)
- `audit_architecture_completion.py`: 2036 LOC (`audit_verifier`)
- `visualize_current_best_pipeline.py`: 1829 LOC (`paper_reporting`)
- `run_pd_only_experiments.py`: 1759 LOC (`experiment_runner`)
- `run_calibration_ablation.py`: 1729 LOC (`experiment_runner`)
- `run_rocket_ablation.py`: 1589 LOC (`experiment_runner`)

## Interpretation

The repo's current architecture is a useful research ledger: many standalone scripts preserve exact historical experiments. That should not be bulk-refactored, because movement would blur provenance and risk accidentally changing archived claims.

The problem is that new work still imports from historical `run_*.py` scripts. This creates hidden API contracts around old experiment files, makes leakage boundaries harder to audit, and encourages copying helpers from whichever script happened to work first.

## Recommended Target Architecture

Keep historical experiment scripts immutable and introduce a narrow layered facade for new work.

- pd_imu/core: paths, targets, split contracts, metrics, cache provenance, fold-local transforms
- pd_imu/datasets: WearGait and external-cohort loaders returning typed subject/visit tables
- pd_imu/features: manifest-backed cache readers/builders with label-use metadata
- pd_imu/pipelines: reusable fold-local PipelineSpec objects for T1, T3, and external validation
- pd_imu/experiments: thin CLI wrappers that bind preregistration, run spec, and write artifacts
- pd_imu/reporting: claim ledger, figure generation, manuscript/export validation

## Migration Order

1. Add facades; do not move old run_*.py scripts in bulk.
2. Extract only code used by canonical and future external-data paths first.
3. Route new experiments through PipelineSpec plus artifact manifest writers.
4. Leave historical failed/leaky scripts as audit archaeology with no new imports from them.
5. Add an import-boundary guard that blocks new run_* -> run_* dependencies except listed legacy exceptions.

## Boundary Rule For New Work

New scripts should import only shared core/facade modules, not other experiment scripts. Existing historical cross-imports remain audit archaeology unless a task explicitly targets cleanup.

Machine-readable report: `results/software_architecture_audit_20260510.json`
