# Repository Guidelines

## Project Structure & Module Organization
This repository is organized around standalone experiment scripts rather than a packaged `src/` tree. Core shared logic lives in `data_split.py`; keep it as the single source of truth for dataset paths, subject splits, and windowing. Use `run_*.py` for experiments (`run_ultimate.py`, `run_dl_experiments.py`, `run_biomechanics.py`, `run_transfer.py`), `paper_fig*.py` for figure generation, and `generate_html_paper.py` to rebuild `paper.html`. Generated plots belong in `figures/`, pulled logs and metrics in `results/`, and narrative notes in Markdown files such as `findings.md`.

## Build, Test, and Development Commands
There is no central build system; run scripts directly.

- `python data_split.py`: regenerate and validate the deterministic dev/test split.
- `python run_biomechanics.py` or `python run_stats_report.py`: rerun a single analysis and refresh JSON/CSV outputs.
- `python generate_html_paper.py`: rebuild the HTML manuscript from current figures.
- `python -m py_compile data_split.py run_*.py`: catch syntax errors before pushing.
- `./gpu.sh run_dl_experiments.py`: sync the repo to the GPU worker and execute a long-running experiment remotely.
- `./gpu.sh --pull`: fetch remote logs and result artifacts back into `results/`.

## Coding Style & Naming Conventions
Follow existing Python style: 4-space indentation, snake_case for functions/files, and ALL_CAPS for module constants such as `DATA_DIR` and `WINDOW_LEN`. Keep new experiment scripts self-contained; avoid creating cross-imports between `run_*.py` files. No repo-wide formatter or linter is configured, so match surrounding style manually. Prefer short, purposeful module docstrings and keep generated artifacts out of git per `.gitignore`.

## Testing Guidelines
There is no formal `tests/` suite yet. Validate changes by rerunning the affected script and checking the expected artifact: JSON in `results/`, plots in `figures/`, or the rendered `paper.html`. For data-split or evaluation changes, confirm subject-level splitting is preserved and report before/after metrics such as MAE and correlation.

## Commit & Pull Request Guidelines
Current history uses short, lowercase subjects (`paper`, `pre simplification`). Keep commit messages equally concise, imperative, and scoped, for example `add transfer baseline summary`. PRs should state which script changed, what dataset split or remote workflow was used, and which outputs were regenerated. Include links to issues when relevant, and attach screenshots or figure samples for manuscript or visualization changes.

## Security & Configuration Tips
Do not commit raw dataset contents, caches, model weights, or credentials such as `synapse_credentials.json`. Large data lives under `data/` on the GPU host; remote access is mediated through `gpu.sh` via `GPU_REMOTE` and `GPU_PORT`.
