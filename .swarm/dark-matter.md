## Dark Matter: Hidden Couplings

Found 20 file pairs that frequently co-change but have no import relationship:

| File A | File B | NPMI | Co-Changes | Lift |
|--------|--------|------|------------|------|
| findings.md | progress.md | 1.000 | 20 | 1.30 |
| pyproject.toml | uv.lock | 1.000 | 3 | 8.67 |
| LEARNINGS.md | data_split.py | 1.000 | 3 | 8.67 |
| CLAUDE.md | task_plan.md | 0.853 | 18 | 1.37 |
| findings.md | task_plan.md | 0.836 | 19 | 1.30 |
| progress.md | task_plan.md | 0.836 | 19 | 1.30 |
| NEW.html | review_report.md | 0.796 | 5 | 3.71 |
| generate_paper.py | review_report.md | 0.796 | 5 | 3.71 |
| NEW.html | NEW2.html | 0.763 | 3 | 5.20 |
| generate_paper.py | pyproject.toml | 0.763 | 3 | 5.20 |
| generate_paper.py | uv.lock | 0.763 | 3 | 5.20 |
| generate_paper.py | run_calibration_ablation.py | 0.763 | 3 | 5.20 |
| paper.html | run_dl_experiments.py | 0.763 | 3 | 5.20 |
| CLAUDE.md | findings.md | 0.713 | 18 | 1.30 |
| CLAUDE.md | progress.md | 0.713 | 18 | 1.30 |
| generate_paper.py | gpu.sh | 0.630 | 3 | 3.90 |
| NEW2.html | review_report.md | 0.608 | 3 | 3.71 |
| pyproject.toml | review_report.md | 0.608 | 3 | 3.71 |
| review_report.md | uv.lock | 0.608 | 3 | 3.71 |
| review_report.md | run_calibration_ablation.py | 0.608 | 3 | 3.71 |

These pairs likely share an architectural concern invisible to static analysis.
Consider adding explicit documentation or extracting the shared concern.