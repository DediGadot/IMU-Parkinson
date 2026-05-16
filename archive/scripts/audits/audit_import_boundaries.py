#!/usr/bin/env python3
"""Guard against new experiment-script import coupling.

The current repository intentionally keeps historical `run_*.py`, `compose_*.py`,
and `cache_*.py` files as a research ledger. Existing cross-script imports are
grandfathered in a baseline artifact; this guard fails only when new non-exception
cross-script edges appear.
"""

from __future__ import annotations

import ast
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from audit_software_architecture import ALLOWED_CROSS_RUN_EXCEPTIONS, classify, root_module


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
BASELINE_JSON = RESULTS / "import_boundary_baseline_20260510.json"
OUT_JSON = RESULTS / "import_boundary_audit_20260510.json"
OUT_MD = RESULTS / "import_boundary_audit_20260510.md"

SOURCE_CATEGORIES = {
    "experiment_runner",
    "canonical_pipeline",
    "composer",
    "cache_builder",
    "audit_verifier",
}

TARGET_CATEGORIES = {
    "experiment_runner",
    "canonical_pipeline",
    "composer",
    "cache_builder",
}

ALLOWED_PACKAGE_LEGACY_IMPORTS = {
    ("pd_imu/core/legacy_experiment_api.py", "run_t1_iter4"),
    ("pd_imu/core/legacy_experiment_api.py", "run_t1_iter33b_8item_chain"),
    ("pd_imu/core/legacy_experiment_api.py", "run_t3_iter2"),
    ("pd_imu/core/legacy_experiment_api.py", "run_t3_iter5_clinical"),
}


def iter_python_files(root: Path) -> list[Path]:
    ignored_parts = {".git", ".venv", "__pycache__", ".mypy_cache", ".pytest_cache"}
    files: list[Path] = []
    for path in root.rglob("*.py"):
        rel = path.relative_to(root)
        if any(part in ignored_parts for part in rel.parts):
            continue
        files.append(rel)
    return sorted(files)


def local_roots_for(root: Path) -> dict[str, list[str]]:
    stems: dict[str, list[str]] = {}
    for path in iter_python_files(root):
        stems.setdefault(path.stem, []).append(path.as_posix())
    return stems


def local_imports(root: Path, path: Path, local_roots: set[str]) -> list[str]:
    try:
        tree = ast.parse((root / path).read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return []
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported = root_module(alias.name)
                if imported in local_roots:
                    imports.add(imported)
        elif isinstance(node, ast.ImportFrom):
            if node.level or not node.module:
                continue
            imported = root_module(node.module)
            if imported in local_roots:
                imports.add(imported)
    return sorted(imports)


def collect_boundary_edges(root: Path = ROOT) -> list[dict[str, str]]:
    stems = local_roots_for(root)
    local_roots = set(stems)
    edges: list[dict[str, str]] = []

    for path in iter_python_files(root):
        source = path.stem
        source_category = classify(path)
        if source_category not in SOURCE_CATEGORIES:
            continue
        for target in local_imports(root, path, local_roots):
            target_path = Path(stems[target][0])
            target_category = classify(target_path)
            if target_category not in TARGET_CATEGORIES:
                continue
            if (source, target) in ALLOWED_CROSS_RUN_EXCEPTIONS:
                continue
            edges.append(
                {
                    "source": source,
                    "source_path": path.as_posix(),
                    "source_category": source_category,
                    "target": target,
                    "target_path": target_path.as_posix(),
                    "target_category": target_category,
                    "edge_key": edge_key(path.as_posix(), target),
                }
            )
    return sorted(edges, key=lambda row: row["edge_key"])


def collect_package_legacy_edges(root: Path = ROOT) -> list[dict[str, str]]:
    """Find pd_imu package imports of historical experiment scripts.

    The package is the target architecture for new work. It may expose a single
    explicit legacy shim while the migration is in progress, but hidden imports
    from arbitrary pd_imu modules back into run/compose/cache scripts would make
    the new package another historical-script dependency surface.
    """

    stems = local_roots_for(root)
    local_roots = set(stems)
    edges: list[dict[str, str]] = []

    for path in iter_python_files(root):
        source_path = path.as_posix()
        if not source_path.startswith("pd_imu/"):
            continue
        for target in local_imports(root, path, local_roots):
            target_path = Path(stems[target][0])
            target_category = classify(target_path)
            if target_category not in TARGET_CATEGORIES:
                continue
            if (source_path, target) in ALLOWED_PACKAGE_LEGACY_IMPORTS:
                continue
            edges.append(
                {
                    "source": path.stem,
                    "source_path": source_path,
                    "source_category": classify(path),
                    "target": target,
                    "target_path": target_path.as_posix(),
                    "target_category": target_category,
                    "edge_key": edge_key(source_path, target),
                }
            )
    return sorted(edges, key=lambda row: row["edge_key"])


def edge_key(source_path: str, target: str) -> str:
    return f"{source_path} -> {target}"


def load_baseline(path: Path = BASELINE_JSON) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def make_baseline(edges: list[dict[str, str]]) -> dict[str, Any]:
    return {
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "script": "audit_import_boundaries.py",
        "policy": "Existing non-exception cross-script imports are grandfathered; new ones fail the guard.",
        "edge_count": len(edges),
        "edges": edges,
        "edge_keys": [edge["edge_key"] for edge in edges],
    }


def compare_edges(
    current_edges: list[dict[str, str]], baseline: dict[str, Any] | None
) -> dict[str, Any]:
    current_by_key = {edge["edge_key"]: edge for edge in current_edges}
    current_keys = set(current_by_key)
    baseline_keys = set(baseline.get("edge_keys", [])) if baseline else set()
    new_keys = sorted(current_keys - baseline_keys)
    removed_keys = sorted(baseline_keys - current_keys)
    return {
        "current_edge_count": len(current_edges),
        "baseline_edge_count": len(baseline_keys),
        "new_edges": [current_by_key[key] for key in new_keys],
        "removed_edge_keys": removed_keys,
    }


def build_report() -> dict[str, Any]:
    RESULTS.mkdir(exist_ok=True)
    current_edges = collect_boundary_edges(ROOT)
    package_legacy_edges = collect_package_legacy_edges(ROOT)
    baseline = load_baseline()
    baseline_created = False
    if baseline is None:
        baseline = make_baseline(current_edges)
        BASELINE_JSON.write_text(json.dumps(baseline, indent=2, sort_keys=True), encoding="utf-8")
        baseline_created = True

    comparison = compare_edges(current_edges, baseline)
    hard_failures = []
    if comparison["new_edges"]:
        hard_failures.append(
            {
                "type": "new_cross_script_imports",
                "n": len(comparison["new_edges"]),
                "edges": comparison["new_edges"],
            }
        )
    if package_legacy_edges:
        hard_failures.append(
            {
                "type": "unauthorized_pd_imu_legacy_imports",
                "n": len(package_legacy_edges),
                "edges": package_legacy_edges,
            }
        )

    return {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "script": "audit_import_boundaries.py",
        "passed": not hard_failures,
        "decision": "import_boundary_guard_passed" if not hard_failures else "import_boundary_guard_failed",
        "baseline": {
            "path": BASELINE_JSON.relative_to(ROOT).as_posix(),
            "created_this_run": baseline_created,
            "edge_count": baseline.get("edge_count"),
        },
        "policy": (
            "New work should import shared core/facade modules instead of importing historical "
            "`run_*`, `compose_*`, or `cache_*` scripts. Existing edges in the baseline remain "
            "grandfathered as audit archaeology."
        ),
        "package_legacy_policy": (
            "The pd_imu package may only import historical experiment scripts through "
            "pd_imu/core/legacy_experiment_api.py. Any other pd_imu -> run/compose/cache edge fails."
        ),
        "comparison": comparison,
        "package_legacy_boundary": {
            "allowed_exception_count": len(ALLOWED_PACKAGE_LEGACY_IMPORTS),
            "unauthorized_edge_count": len(package_legacy_edges),
            "unauthorized_edges": package_legacy_edges,
        },
        "hard_failures": hard_failures,
    }


def write_markdown(report: dict[str, Any]) -> None:
    comparison = report["comparison"]
    lines = [
        "# Import Boundary Audit - 2026-05-10",
        "",
        report["policy"],
        "",
        f"- Passed: `{report['passed']}`",
        f"- Decision: `{report['decision']}`",
        f"- Baseline: `{report['baseline']['path']}`",
        f"- Baseline created this run: `{report['baseline']['created_this_run']}`",
        f"- Baseline edge count: `{comparison['baseline_edge_count']}`",
        f"- Current edge count: `{comparison['current_edge_count']}`",
        f"- New edges: `{len(comparison['new_edges'])}`",
        f"- Removed baseline edges: `{len(comparison['removed_edge_keys'])}`",
        f"- Unauthorized `pd_imu` legacy imports: `{report['package_legacy_boundary']['unauthorized_edge_count']}`",
        "",
        "## New Edges",
        "",
    ]
    if comparison["new_edges"]:
        for edge in comparison["new_edges"]:
            lines.append(
                f"- `{edge['source_path']}` imports `{edge['target']}` "
                f"(`{edge['source_category']}` -> `{edge['target_category']}`)"
            )
    else:
        lines.append("None.")

    lines.extend(
        [
            "",
            "## pd_imu Package Boundary",
            "",
            report["package_legacy_policy"],
            "",
        ]
    )
    if report["package_legacy_boundary"]["unauthorized_edges"]:
        for edge in report["package_legacy_boundary"]["unauthorized_edges"]:
            lines.append(
                f"- `{edge['source_path']}` imports `{edge['target']}` "
                f"(`{edge['source_category']}` -> `{edge['target_category']}`)"
            )
    else:
        lines.append("No unauthorized package-to-legacy imports.")

    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "A passing result does not mean the current architecture is clean. It means no new cross-script coupling has been introduced beyond the baseline. The baseline documents historical debt while allowing the new layered-facade architecture to be enforced going forward.",
            "",
            f"Machine-readable report: `{OUT_JSON.relative_to(ROOT).as_posix()}`",
            "",
        ]
    )
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    report = build_report()
    OUT_JSON.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    write_markdown(report)
    print(f"Wrote {OUT_JSON}")
    print(f"Wrote {OUT_MD}")
    print(
        json.dumps(
            {
                "passed": report["passed"],
                "decision": report["decision"],
                "baseline_created": report["baseline"]["created_this_run"],
                "baseline_edge_count": report["comparison"]["baseline_edge_count"],
                "current_edge_count": report["comparison"]["current_edge_count"],
                "new_edges": len(report["comparison"]["new_edges"]),
            },
            indent=2,
            sort_keys=True,
        )
    )
    if report["hard_failures"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
