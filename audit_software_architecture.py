#!/usr/bin/env python3
"""Audit repository software architecture and recommend a safer target layout.

This is intentionally non-mutating. It quantifies the current flat experiment
surface and script-to-script coupling so architecture recommendations are tied
to actual repository evidence.
"""

from __future__ import annotations

import ast
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
OUT_JSON = RESULTS / "software_architecture_audit_20260510.json"
OUT_MD = RESULTS / "software_architecture_audit_20260510.md"

CORE_MODULES = {
    "data_split",
    "project_paths",
    "updrs_columns",
    "eval_utils",
    "inductive_lib",
    "cache_provenance",
    "lgb_ccc_objective_v2",
}

CANONICAL_SCRIPTS = {
    "compose_t1_iter12_honest",
    "run_t1_iter34_hybrid_8item_multibase",
    "run_t3_iter47_invalid_code_fix",
    "run_t3_iter41_target_fix",
    "run_t3_iter5_clinical",
    "run_t3_iter16_site_ipw",
}

ALLOWED_CROSS_RUN_EXCEPTIONS = {
    ("run_clean_benchmark", "run_ablation_v2"),
    ("run_ablation_v3", "run_ablation_v2"),
    ("run_paper_supplements", "run_ablation_v3"),
    ("run_paper_supplements", "run_proven_stack"),
}


def iter_python_files() -> list[Path]:
    ignored_parts = {".git", ".venv", "__pycache__", ".mypy_cache", ".pytest_cache"}
    files: list[Path] = []
    for path in ROOT.rglob("*.py"):
        rel = path.relative_to(ROOT)
        if any(part in ignored_parts for part in rel.parts):
            continue
        files.append(rel)
    return sorted(files)


def module_name(path: Path) -> str:
    if path.name == "__init__.py":
        return ".".join(path.with_suffix("").parts[:-1])
    return ".".join(path.with_suffix("").parts)


def root_module(import_name: str) -> str:
    return import_name.split(".", 1)[0]


def classify(path: Path) -> str:
    stem = path.stem
    if path.parts[0] == "pd_imu":
        return "architecture_facade"
    if path.parts[0] == "tests":
        return "tests"
    if path.parts[0] == "scripts":
        return "support_script"
    if stem in CORE_MODULES:
        return "shared_core"
    if stem in CANONICAL_SCRIPTS:
        return "canonical_pipeline"
    if stem.startswith("run_"):
        return "experiment_runner"
    if stem.startswith("cache_"):
        return "cache_builder"
    if stem.startswith("compose_"):
        return "composer"
    if stem.startswith("audit_") or stem.startswith("verify_") or stem.startswith("check_"):
        return "audit_verifier"
    if stem.startswith("generate_") or stem.startswith("paper_") or stem.startswith("visualize_") or stem == "render_current_paper":
        return "paper_reporting"
    if stem.startswith("src_"):
        return "legacy_src_module"
    if stem.startswith("test_"):
        return "ad_hoc_test_script"
    return "miscellaneous"


def count_lines(path: Path) -> int:
    try:
        return len((ROOT / path).read_text(encoding="utf-8", errors="replace").splitlines())
    except OSError:
        return 0


def local_imports(path: Path, local_roots: set[str]) -> list[str]:
    try:
        tree = ast.parse((ROOT / path).read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return []
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = root_module(alias.name)
                if root in local_roots:
                    imports.add(root)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                continue
            if not node.module:
                continue
            root = root_module(node.module)
            if root in local_roots:
                imports.add(root)
    return sorted(imports)


def build_report() -> dict[str, Any]:
    py_files = iter_python_files()
    module_to_path = {module_name(path): path.as_posix() for path in py_files}
    stem_to_paths: dict[str, list[str]] = defaultdict(list)
    for path in py_files:
        stem_to_paths[path.stem].append(path.as_posix())
    local_roots = set(stem_to_paths)

    file_rows: list[dict[str, Any]] = []
    import_edges: list[dict[str, str]] = []
    syntax_unreadable: list[str] = []

    for path in py_files:
        stem = path.stem
        category = classify(path)
        imports = local_imports(path, local_roots)
        try:
            ast.parse((ROOT / path).read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            syntax_unreadable.append(path.as_posix())
        for imported in imports:
            import_edges.append(
                {
                    "source": stem,
                    "source_path": path.as_posix(),
                    "source_category": category,
                    "target": imported,
                    "target_category": classify(Path(stem_to_paths[imported][0])),
                }
            )
        file_rows.append(
            {
                "path": path.as_posix(),
                "module": module_name(path),
                "stem": stem,
                "category": category,
                "loc": count_lines(path),
                "local_imports": imports,
            }
        )

    category_counts = Counter(row["category"] for row in file_rows)
    category_loc = Counter()
    for row in file_rows:
        category_loc[row["category"]] += row["loc"]

    target_fanin = Counter(edge["target"] for edge in import_edges)
    source_fanout = Counter(edge["source"] for edge in import_edges)
    cross_script_edges = [
        edge
        for edge in import_edges
        if edge["target_category"] in {"experiment_runner", "canonical_pipeline", "composer", "cache_builder"}
        and edge["source_category"]
        in {"experiment_runner", "canonical_pipeline", "composer", "cache_builder", "audit_verifier"}
    ]
    non_exception_cross_run_edges = [
        edge
        for edge in cross_script_edges
        if (edge["source"], edge["target"]) not in ALLOWED_CROSS_RUN_EXCEPTIONS
    ]

    high_loc_files = sorted(file_rows, key=lambda row: row["loc"], reverse=True)[:25]
    high_fanin = target_fanin.most_common(25)
    high_fanout = source_fanout.most_common(25)

    shared_core_rows = [row for row in file_rows if row["category"] == "shared_core"]
    canonical_rows = [row for row in file_rows if row["category"] == "canonical_pipeline"]

    decision = (
        "recommend_layered_facade_no_mass_move"
        if non_exception_cross_run_edges
        else "current_flat_scripts_acceptable_with_minor_guards"
    )

    return {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "script": "audit_software_architecture.py",
        "passed": True,
        "decision": decision,
        "summary": {
            "python_files": len(py_files),
            "total_loc": sum(row["loc"] for row in file_rows),
            "category_counts": dict(sorted(category_counts.items())),
            "category_loc": dict(sorted(category_loc.items())),
            "local_import_edges": len(import_edges),
            "cross_script_edges": len(cross_script_edges),
            "non_exception_cross_script_edges": len(non_exception_cross_run_edges),
            "syntax_unreadable_count": len(syntax_unreadable),
        },
        "shared_core": shared_core_rows,
        "canonical_pipelines": canonical_rows,
        "high_loc_files": high_loc_files,
        "high_fanin": [{"module": name, "count": count} for name, count in high_fanin],
        "high_fanout": [{"module": name, "count": count} for name, count in high_fanout],
        "cross_script_edges_sample": non_exception_cross_run_edges[:80],
        "syntax_unreadable": syntax_unreadable,
        "recommended_target_architecture": {
            "principle": "Keep historical experiment scripts immutable and introduce a narrow layered facade for new work.",
            "layers": [
                "pd_imu/core: paths, targets, split contracts, metrics, cache provenance, fold-local transforms",
                "pd_imu/datasets: WearGait and external-cohort loaders returning typed subject/visit tables",
                "pd_imu/features: manifest-backed cache readers/builders with label-use metadata",
                "pd_imu/pipelines: reusable fold-local PipelineSpec objects for T1, T3, and external validation",
                "pd_imu/experiments: thin CLI wrappers that bind preregistration, run spec, and write artifacts",
                "pd_imu/reporting: claim ledger, figure generation, manuscript/export validation",
            ],
            "migration_order": [
                "Add facades; do not move old run_*.py scripts in bulk.",
                "Extract only code used by canonical and future external-data paths first.",
                "Route new experiments through PipelineSpec plus artifact manifest writers.",
                "Leave historical failed/leaky scripts as audit archaeology with no new imports from them.",
                "Add an import-boundary guard that blocks new run_* -> run_* dependencies except listed legacy exceptions.",
            ],
        },
    }


def write_markdown(report: dict[str, Any]) -> None:
    summary = report["summary"]
    lines = [
        "# Software Architecture Audit - 2026-05-10",
        "",
        "This audit quantifies the repository architecture without changing experiment code.",
        "",
        f"- Decision: `{report['decision']}`",
        f"- Python files: `{summary['python_files']}`",
        f"- Total Python LOC: `{summary['total_loc']}`",
        f"- Local import edges: `{summary['local_import_edges']}`",
        f"- Cross-script edges: `{summary['cross_script_edges']}`",
        f"- Non-exception cross-script edges: `{summary['non_exception_cross_script_edges']}`",
        f"- Syntax-unreadable files: `{summary['syntax_unreadable_count']}`",
        "",
        "## Category Counts",
        "",
    ]
    for category, count in summary["category_counts"].items():
        lines.append(f"- `{category}`: {count} files, {summary['category_loc'].get(category, 0)} LOC")

    lines.extend(["", "## Shared Core", ""])
    for row in report["shared_core"]:
        lines.append(f"- `{row['path']}`: {row['loc']} LOC")

    lines.extend(["", "## Canonical Pipelines", ""])
    for row in report["canonical_pipelines"]:
        lines.append(f"- `{row['path']}`: {row['loc']} LOC")

    lines.extend(["", "## Highest Fan-In Local Modules", ""])
    for row in report["high_fanin"][:15]:
        lines.append(f"- `{row['module']}`: imported by {row['count']} local files")

    lines.extend(["", "## Largest Files", ""])
    for row in report["high_loc_files"][:15]:
        lines.append(f"- `{row['path']}`: {row['loc']} LOC (`{row['category']}`)")

    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "The repo's current architecture is a useful research ledger: many standalone scripts preserve exact historical experiments. That should not be bulk-refactored, because movement would blur provenance and risk accidentally changing archived claims.",
            "",
            "The problem is that new work still imports from historical `run_*.py` scripts. This creates hidden API contracts around old experiment files, makes leakage boundaries harder to audit, and encourages copying helpers from whichever script happened to work first.",
            "",
            "## Recommended Target Architecture",
            "",
        ]
    )
    target = report["recommended_target_architecture"]
    lines.append(target["principle"])
    lines.append("")
    for layer in target["layers"]:
        lines.append(f"- {layer}")
    lines.extend(["", "## Migration Order", ""])
    for idx, step in enumerate(target["migration_order"], start=1):
        lines.append(f"{idx}. {step}")

    lines.extend(
        [
            "",
            "## Boundary Rule For New Work",
            "",
            "New scripts should import only shared core/facade modules, not other experiment scripts. Existing historical cross-imports remain audit archaeology unless a task explicitly targets cleanup.",
            "",
            f"Machine-readable report: `{OUT_JSON.relative_to(ROOT).as_posix()}`",
            "",
        ]
    )
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    RESULTS.mkdir(exist_ok=True)
    report = build_report()
    OUT_JSON.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    write_markdown(report)
    print(f"Wrote {OUT_JSON}")
    print(f"Wrote {OUT_MD}")
    print(json.dumps(report["summary"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
