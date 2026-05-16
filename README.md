# Current Post-Audit WearGait-PD Benchmark

This repository is a WearGait-PD Parkinson's motor-severity research codebase. It now functions as a leakage-audited benchmark and paper artifact store, not as evidence for the original healthy-control-anchored SSL/ranking claims.

The old XGBRanker/healthy-control-anchor results, including T1 CCC `0.868` and T3 CCC `0.776`, are legacy/retracted/pre-audit archaeology. They were target-contaminated because the ranking representation was trained with all subjects before the reported LOOCV evaluation. Do not cite them as deployable or current results.

## Current Truth

| Claim surface | Script/artifact | Status | N | CCC | MAE | Notes |
|---------------|-----------------|--------|---|-----|-----|-------|
| **T1 canonical floor** | `compose_t1_iter12_honest.py` / `results/t1_iter12_honest_composite.json` | current canonical | 94 | `0.6550` | `1.561` | One coherent iter8 batch, no swaps. |
| **T1 corrected candidate** | `run_t1_iter34_hybrid_8item_multibase.py` / `results/lockbox_t1_iter34_hybrid_20260510_233019.json` | candidate/caveated only | 92 | `0.7170` | `1.736` | Valid-auxiliary rerun; above the floor but lower than the superseded N=93 iter34 value. |
| **T3 current** | `run_t3_iter47_invalid_code_fix.py` / `results/iter47_invalidcode_20260508_194605.json` | current corrected internal result | 95 | `0.3784` | `7.528` | Valid-range target correction after the iter5 target audit. |
| **T3 current LOSO** | `run_t3_iter47_invalid_code_fix.py` / `results/iter47_invalidcode_loso_20260508_195424.json` | current transportability sensitivity | 95 | `0.150` | n/a | Two-way LOSO under the corrected T3 target. |

Original iter34 `0.7366` (N=93) was superseded for current-candidate citation by the hygiene-corrected N=92 rerun after the auxiliary item15 valid-range audit. Older T3 iter5 `0.5227` and iter16 LOSO `0.341` were superseded by the iter47 valid-range correction. Older `generate_paper*.py` / `NEW*.html` outputs are historical snapshots only. The current manuscript route is:

```bash
uv run python render_current_paper.py
```

Outputs:
- `CURRENT_PAPER.html` - authoritative current post-audit HTML manuscript
- `results/current_paper_export/manifest.json` - renderer validation manifest

## Dataset

**WearGait-PD** ([Synapse syn55052683](https://www.synapse.org/#!Synapse:syn55052683)) is a controlled-gait dataset with complete MDS-UPDRS Part III scores.

- **178 subjects** (98 PD, 80 healthy controls), 13 Xsens MTw Awinda IMUs at 100 Hz
- **5 gait tasks**: self-paced walking, hurried-pace walking, Timed Up-and-Go, balance, tandem gait
- **78 IMU channels**: triaxial accelerometer and gyroscope per sensor
- **Clinical fields**: MDS-UPDRS Part III, item/sub-item scores, Hoehn & Yahr, demographics, and related intake variables

### Subject Counts Across Evaluation Protocols

Different protocols yield slightly different N because of missing item-level UPDRS data and post-audit valid-range filtering.

| Protocol | N (PD) | Current use |
|----------|--------|-------------|
| T1 iter12 honest LOOCV | 94 | canonical T1 floor |
| T1 iter34 hygiene-corrected hybrid LOOCV | 92 | corrected T1 candidate only |
| T3 iter47 valid-range LOOCV | 95 | current corrected internal T3 |
| Full PD cohort availability | 98 | historical and screening contexts |

## Repository Structure

```
├── data_split.py               # Shared: clinical parsing, windowing, deterministic splits
├── project_paths.py            # Shared: centralized paths with env overrides
├── updrs_columns.py            # Shared: robust UPDRS column name resolution
├── inductive_lib.py            # Shared: fold-local imputation, normalization, metrics, null gates
│
├── compose_t1_iter12_honest.py # Current canonical T1 floor
├── run_t1_iter34_hybrid_8item_multibase.py # Corrected T1 candidate, caveated only
├── run_t3_iter47_invalid_code_fix.py       # Current corrected T3 LOOCV/LOSO
├── run_t3_iter5_clinical.py                # Historical iter5 T3 architecture, superseded target
├── run_t3_iter16_site_ipw.py               # Historical iter5 LOSO/IPW sensitivity, superseded target
├── run_compression_ablation.py             # Historical pre-audit SSL ranking reproduction only
│
├── render_current_paper.py     # Current post-audit paper renderer -> CURRENT_PAPER.html
├── generate_paper.py           # Historical pre-audit paper generator -> PAPER.html
├── generate_paper_v4.py        # Legacy/stale pre-audit generator -> NEW4.html
├── paper.md                    # Current Markdown manuscript source
│
├── audit_readme_claim_routing.py          # README current-vs-legacy claim guard
├── audit_paper_generator_routing.py       # Paper-renderer route guard
├── audit_canonical_claim_consistency.py   # Active-scope canonical claim guard
├── verify_current_goal_state.py           # Thread-level state verifier
├── visualize_current_best_pipeline.py     # Unified current-state dashboard
│
├── gpu.sh                      # Remote GPU deployment script
├── synapse_download.py         # WearGait-PD dataset download helper
├── requirements-gpu.txt        # Pinned GPU dependencies
├── pyproject.toml              # Local dependencies
│
├── results/                    # Experiment outputs, audit reports, manifests, figures
├── figures/                    # Historical and current figure assets
└── tests/                      # Unit tests
```

## Setup

### Local Environment

```bash
git clone <repository-url> && cd medical
uv sync
```

Use `uv run ...` for local Python commands.

### Remote GPU Environment

The codebase supports a local/remote split: code lives on your machine, heavy experiments run on a remote GPU via SSH.

```bash
export GPU_REMOTE=user@your-gpu-server
export GPU_PORT=22
./gpu.sh --setup
```

GPU server requirements:
- NVIDIA GPU with CUDA 12.x and 8 GB+ VRAM
- Python 3.10+
- 32 GB+ system RAM
- About 100 GB disk for raw WearGait-PD data, dependencies, caches, and results

## Data Access

You must accept the WearGait-PD Terms of Use on the [Synapse dataset page](https://www.synapse.org/#!Synapse:syn55052683) before the API will authorize downloads.

```bash
export SYNAPSE_TOKEN=your_token_here

# If using the remote GPU:
./gpu.sh synapse_download.py

# If running locally:
uv run python synapse_download.py
```

Use `WEARGAIT_DATA_DIR`, `WEARGAIT_RESULTS_DIR`, and the helpers in `project_paths.py` rather than hard-coded repo-root paths for new work.

## Current Reproduction Commands

### Paper And Claim Guards

```bash
uv run python render_current_paper.py
uv run python audit_readme_claim_routing.py
uv run python audit_paper_generator_routing.py
uv run python audit_canonical_claim_consistency.py
uv run python visualize_current_best_pipeline.py
uv run python audit_prompt_objective_evidence.py
uv run python verify_current_goal_state.py
```

### Tests And Syntax

```bash
uv run pytest tests/ -v
uv run pytest tests/test_inductive_leakage_fix.py tests/test_inductive_lib.py -v
uv run pytest tests/test_data_split.py tests/test_project_paths.py -v
# legacy syntax-only coverage includes generate_paper_v4.py
uv run python -m py_compile data_split.py project_paths.py inductive_lib.py run_*.py render_current_paper.py generate_paper_v4.py
```

### Remote State

```bash
./gpu.sh --status
./gpu.sh --log
./gpu.sh --pull
```

## Current Modeling Discipline

- Always use subject-level splits.
- Fit imputers, scalers, feature selectors, rankers, bins, calibration parameters, and meta-learners inside the fold.
- Treat healthy controls as diagnostic-only unless a new fold-clean experiment proves otherwise.
- Do not use global XGBRanker ranks or leaf features for an inductive/deployment claim; that route is invalid/target-contaminated for current claims.
- Do not promote sensitivity winners unless they survive the repo's pre-registration and lockbox rules.
- Every reusable cache feeding an inductive headline must have a clean manifest sidecar.

## Historical Pre-Audit Archaeology

This section preserves the old route for reproducibility audits only. It is not the current paper route and not a deployable result.

### Historical SSL Ranking Pipeline

The old two-stage semi-supervised learning (SSL) ranking pipeline trained an XGBRanker on all 178 subjects, including healthy controls and the held-out PD subject's rank label, then used the leaf features in a PD-only LOOCV LightGBM regressor. That transductive Stage 1 was later judged target-contaminated for deployment-style claims.

Historical, retracted/pre-audit headline numbers from that route included:

| Historical target | Historical CCC | Why not current |
|-------------------|----------------|-----------------|
| T1 direct observable | `0.868` | target-contaminated SSL/ranking route; superseded by T1 iter12 `0.6550` canonical floor and iter34 `0.7366` candidate |
| T2 broad observable | `0.852` | target-contaminated SSL/ranking route |
| T3 total UPDRS-III | `0.776` | target-contaminated SSL/ranking route; superseded by corrected T3 iter47 `0.3784` |

The historical command sequence is retained only for archaeology:

```bash
./gpu.sh run_compression_ablation.py --phase 0   # historical P0 baseline
./gpu.sh run_compression_ablation.py --phase 1   # historical P1 ordinal
./gpu.sh run_compression_ablation.py --phase 3   # historical P3 SMOGN
./gpu.sh run_compression_ablation.py --phase 4   # historical P4 NGBoost
./gpu.sh run_compression_ablation.py --phase 5   # historical P5 SSL ranking, not current evidence
```

Historical outputs include `results/compression_P{0-5}_TT{1-3}.json` and `results/compression_P5_TT{1-3}_loocv.json`. Treat these as pre-audit reproduction artifacts.

### Historical Cross-Dataset Comparison Tables

Rows such as "This work (T3, SSL)" with CCC `0.776`, "This work (T1, SSL)" with CCC `0.868`, and T1 MAE `0.986` are legacy/retracted/pre-audit claims. They should appear only with local context saying historical, target-contaminated, not current, or do not cite.

## `gpu.sh` Reference

```bash
./gpu.sh <script.py> [args]    # Deploy code + run on GPU server
./gpu.sh --pull                # Fetch results to local ./results/
./gpu.sh --push-cache          # Upload cached feature artifacts to GPU server
./gpu.sh --status              # Check GPU utilization and running jobs
./gpu.sh --log                 # Tail latest remote log
./gpu.sh --ssh                 # Open shell on GPU server
./gpu.sh --setup               # Provision a fresh GPU server
./gpu.sh --nuke                # Kill all Python jobs on remote
```

To swap GPU servers:

```bash
export GPU_REMOTE=user@new-server GPU_PORT=22
./gpu.sh --setup
```

## Troubleshooting

| Issue | Solution |
|-------|----------|
| `synapse_download.py` fails with 403 | Accept Terms of Use on the Synapse dataset page first. |
| CUDA OOM during embedding extraction | Reduce batch size in the relevant runner, or use a GPU with more VRAM. |
| `ModuleNotFoundError` for GPU-only packages | Install the pinned GPU requirements with `uv pip install -r requirements-gpu.txt`. |
| Experiment produces different numbers | Check the current split file, cache provenance sidecars, and the relevant pre-registration JSON before interpreting the result. |
| `gpu.sh` hangs on deploy | Check SSH connectivity: `ssh -p $GPU_PORT $GPU_REMOTE echo ok`. |

## Citation

```bibtex
@article{wrgaitpd2026,
  title={Leakage-audited wearable Parkinson's motor-severity regression on WearGait-PD},
  year={2026},
  note={Current post-audit manuscript is rendered with render_current_paper.py}
}
```

## License

[To be determined]
