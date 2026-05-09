"""Audit cache-like artifacts reachable through local import closures.

`audit_cache_consumer_guards.py` checks direct references inside each Python
file. This companion audit starts from current headline/reportable entrypoints,
walks local imports with AST parsing, and records cache-like artifacts referenced
anywhere in the reachable source files.

The result is intentionally conservative: a reference in an imported helper is
not automatically an executed dependency for every entrypoint. It is a
provenance boundary that needs either a manifest, a fail-closed guard, or a
script-specific explanation before a future headline is described as
cache-manifest-clean.
"""
from __future__ import annotations

import ast
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
MANIFEST_AUDIT = RESULTS / "cache_manifest_audit_20260508.json"
OUT_JSON = RESULTS / "transitive_cache_dependency_audit_20260508.json"
OUT_MD = RESULTS / "transitive_cache_dependency_audit_20260508.md"

ENTRYPOINTS = [
    "compose_t1_iter12_honest.py",
    "run_t1_iter34_hybrid_8item_multibase.py",
    "run_t1_iter46_et_robust.py",
    "run_t3_iter47_invalid_code_fix.py",
    "run_t3_iter41_target_fix.py",
    "run_t3_iter5_clinical.py",
    "run_t3_iter16_site_ipw.py",
    "compose_t1_iter14_fog.py",
    "compose_t1_iter15_harnet.py",
    "run_t3_iter23_clinical_ablation.py",
    "run_t3_iter24_stage2_forced.py",
    "run_t3_iter49_cops.py",
]

REPORTABLE_ENTRYPOINTS = {
    "compose_t1_iter12_honest.py": "canonical_t1_current_floor",
    "run_t1_iter34_hybrid_8item_multibase.py": "strongest_t1_candidate_caveated",
    "run_t1_iter46_et_robust.py": "t1_diagnostic_robustification",
    "run_t3_iter47_invalid_code_fix.py": "canonical_t3_validrange_audit_truth",
    "run_t3_iter41_target_fix.py": "superseded_t3_corrected_target_audit",
    "run_t3_iter5_clinical.py": "historical_t3_target_contaminated",
    "run_t3_iter16_site_ipw.py": "historical_t3_target_contaminated_loso",
    "compose_t1_iter14_fog.py": "guarded_safe_cache_null_screen",
    "compose_t1_iter15_harnet.py": "guarded_safe_cache_null_screen",
    "run_t3_iter23_clinical_ablation.py": "guarded_safe_cache_null_screen",
    "run_t3_iter24_stage2_forced.py": "guarded_safe_cache_null_screen",
    "run_t3_iter49_cops.py": "external_zero_shot_diagnostic",
}

TOKEN_BOUNDARY = re.compile(r"[A-Za-z0-9_.-]")
RUNTIME_READ_RE = re.compile(
    r"\b(pd\.read_csv|read_csv|np\.load|np\.loadtxt|open\(|read_text\(|read_parquet|read_feather)\b"
)


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def root_python_modules() -> dict[str, Path]:
    modules: dict[str, Path] = {}
    for path in ROOT.glob("*.py"):
        modules[path.stem] = path
    return modules


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def local_imports(path: Path, module_index: dict[str, Path]) -> tuple[list[Path], str | None]:
    try:
        tree = ast.parse(read_text(path), filename=str(path))
    except SyntaxError as exc:
        return [], f"{exc.__class__.__name__}: {exc}"

    imports: set[Path] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                head = alias.name.split(".")[0]
                if head in module_index:
                    imports.add(module_index[head])
        elif isinstance(node, ast.ImportFrom):
            if node.level != 0 or not node.module:
                continue
            head = node.module.split(".")[0]
            if head in module_index:
                imports.add(module_index[head])
    return sorted(imports, key=lambda p: rel(p)), None


def import_closure(entrypoint: Path, module_index: dict[str, Path]) -> dict[str, Any]:
    stack = [entrypoint]
    seen: set[Path] = set()
    edges: dict[str, list[str]] = {}
    parse_errors: dict[str, str] = {}

    while stack:
        path = stack.pop()
        if path in seen:
            continue
        seen.add(path)
        imports, error = local_imports(path, module_index)
        if error:
            parse_errors[rel(path)] = error
            continue
        edges[rel(path)] = [rel(p) for p in imports]
        for imported in reversed(imports):
            if imported not in seen:
                stack.append(imported)

    return {
        "files": sorted(rel(p) for p in seen),
        "edges": {k: sorted(v) for k, v in sorted(edges.items())},
        "parse_errors": parse_errors,
    }


def artifact_tokens(artifact: str) -> list[str]:
    path = Path(artifact)
    tokens = [artifact, path.name]
    if artifact.startswith("results/"):
        tokens.append(artifact[len("results/") :])
    # Preserve order but remove duplicates.
    return list(dict.fromkeys(t for t in tokens if t))


def token_in_line(line: str, token: str) -> bool:
    start = 0
    while True:
        idx = line.find(token, start)
        if idx < 0:
            return False
        before = line[idx - 1] if idx > 0 else ""
        after_idx = idx + len(token)
        after = line[after_idx] if after_idx < len(line) else ""
        if not before or not TOKEN_BOUNDARY.match(before):
            if not after or not TOKEN_BOUNDARY.match(after):
                return True
        start = idx + 1


def matching_lines(text: str, tokens: list[str], max_refs: int = 8) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        if any(token_in_line(line, token) for token in tokens):
            refs.append({"line": lineno, "text": line.strip()[:240]})
            if len(refs) >= max_refs:
                break
    return refs


def runtime_read_near_refs(text: str, refs: list[dict[str, Any]]) -> bool:
    lines = text.splitlines()
    for ref in refs:
        idx = int(ref["line"]) - 1
        window = "\n".join(lines[max(0, idx - 12) : min(len(lines), idx + 80)])
        if RUNTIME_READ_RE.search(window):
            return True
    return False


def classify_entrypoint(cache_refs: list[dict[str, Any]], entrypoint: str) -> tuple[str, str]:
    if not cache_refs:
        return (
            "no_cache_like_artifacts_in_import_closure",
            "No cache-like artifact from the manifest audit appears in the local import closure.",
        )

    diagnostic = [
        ref
        for ref in cache_refs
        if ref["artifact_status"] != "manifest_complete_clean_by_construction"
    ]
    direct_diagnostic = [
        ref for ref in diagnostic if entrypoint in ref["referenced_in_files"]
    ]
    transitive_diagnostic = [
        ref for ref in diagnostic if entrypoint not in ref["referenced_in_files"]
    ]
    unguarded_clean = [
        ref
        for ref in cache_refs
        if ref["artifact_status"] == "manifest_complete_clean_by_construction"
        and not ref["guard_present_in_any_referencing_file"]
    ]

    if direct_diagnostic:
        return (
            "entrypoint_direct_diagnostic_cache_reference",
            "The entrypoint source directly references missing/partial-manifest cache-like artifacts; reportable reuse needs regeneration/backfill or a stronger diagnostic-only caveat.",
        )
    if transitive_diagnostic:
        return (
            "import_closure_contains_diagnostic_cache_reference",
            "Imported local helpers reference missing/partial-manifest cache-like artifacts. This is a conservative reachability finding; script-specific call paths decide whether the cache is executed.",
        )
    if unguarded_clean:
        return (
            "clean_cache_reference_without_universal_guard",
            "Only clean-manifest caches are referenced, but at least one referencing file lacks the shared fail-closed guard.",
        )
    return (
        "guarded_clean_import_closure",
        "All cache-like artifacts in the import closure have complete clean manifests and are referenced from files that contain the shared guard.",
    )


def analyze_entrypoint(
    entrypoint: str,
    artifact_rows: dict[str, dict[str, Any]],
    module_index: dict[str, Path],
) -> dict[str, Any]:
    entry_path = ROOT / entrypoint
    closure = import_closure(entry_path, module_index)
    cache_refs: list[dict[str, Any]] = []

    for artifact, row in artifact_rows.items():
        tokens = artifact_tokens(artifact)
        referenced_by_file: dict[str, dict[str, Any]] = {}
        for file_rel in closure["files"]:
            path = ROOT / file_rel
            text = read_text(path)
            refs = matching_lines(text, tokens)
            if not refs:
                continue
            referenced_by_file[file_rel] = {
                "line_refs": refs,
                "guard_present": "require_cache_manifest" in text,
                "runtime_read_near_reference": runtime_read_near_refs(text, refs),
            }
        if not referenced_by_file:
            continue
        cache_refs.append(
            {
                "artifact": artifact,
                "artifact_status": row.get("status"),
                "manifest": row.get("manifest"),
                "referenced_in_files": sorted(referenced_by_file),
                "referenced_by_entrypoint_file": entrypoint in referenced_by_file,
                "guard_present_in_any_referencing_file": any(
                    item["guard_present"] for item in referenced_by_file.values()
                ),
                "runtime_read_near_any_reference": any(
                    item["runtime_read_near_reference"] for item in referenced_by_file.values()
                ),
                "file_references": referenced_by_file,
            }
        )

    cache_refs = sorted(cache_refs, key=lambda row: row["artifact"])
    classification, interpretation = classify_entrypoint(cache_refs, entrypoint)
    diagnostic_refs = [
        row
        for row in cache_refs
        if row["artifact_status"] != "manifest_complete_clean_by_construction"
    ]
    clean_refs = [
        row
        for row in cache_refs
        if row["artifact_status"] == "manifest_complete_clean_by_construction"
    ]
    return {
        "entrypoint": entrypoint,
        "entrypoint_role": REPORTABLE_ENTRYPOINTS.get(entrypoint, "unclassified"),
        "classification": classification,
        "interpretation": interpretation,
        "n_dependency_files": len(closure["files"]),
        "dependency_files": closure["files"],
        "import_edges": closure["edges"],
        "parse_errors": closure["parse_errors"],
        "n_cache_references": len(cache_refs),
        "uses_diagnostic_or_partial_cache": bool(diagnostic_refs),
        "uses_missing_manifest_cache": any(
            row["artifact_status"] == "missing_manifest_diagnostic_only"
            for row in diagnostic_refs
        ),
        "diagnostic_or_partial_cache_artifacts": [
            row["artifact"] for row in diagnostic_refs
        ],
        "clean_manifest_cache_artifacts": [row["artifact"] for row in clean_refs],
        "cache_references": cache_refs,
    }


def main() -> None:
    audit = read_json(MANIFEST_AUDIT)
    artifact_rows = {
        row["artifact"]: row
        for row in audit.get("artifacts", [])
        if row.get("artifact")
    }
    module_index = root_python_modules()

    entrypoint_reports = [
        analyze_entrypoint(entrypoint, artifact_rows, module_index)
        for entrypoint in ENTRYPOINTS
    ]
    counts: dict[str, int] = {}
    for report in entrypoint_reports:
        counts[report["classification"]] = counts.get(report["classification"], 0) + 1

    direct_diagnostic = [
        report["entrypoint"]
        for report in entrypoint_reports
        if report["classification"] == "entrypoint_direct_diagnostic_cache_reference"
    ]
    transitive_diagnostic = [
        report["entrypoint"]
        for report in entrypoint_reports
        if report["classification"] == "import_closure_contains_diagnostic_cache_reference"
    ]

    report = {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "script": "audit_transitive_cache_dependencies.py",
        "source_manifest_audit": str(MANIFEST_AUDIT.relative_to(ROOT)),
        "entrypoints": ENTRYPOINTS,
        "classification_counts": counts,
        "direct_diagnostic_entrypoints": direct_diagnostic,
        "transitive_diagnostic_entrypoints": transitive_diagnostic,
        "verdict": (
            "Direct cache-consumer guard status is not enough for provenance claims. "
            "Current headline/candidate entrypoints have import closures that can reach "
            "diagnostic-only cache paths through historical helper modules; this should be "
            "disclosed as conservative static reachability and resolved by cache backfill, "
            "regeneration, or narrower helper extraction before claiming cache-manifest-clean "
            "future headlines."
        ),
        "entrypoint_reports": entrypoint_reports,
    }
    OUT_JSON.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")

    lines = [
        "# Transitive Cache Dependency Audit — 2026-05-08",
        "",
        "`audit_cache_consumer_guards.py` scans direct cache references. This audit walks local Python imports from current headline/reportable entrypoints and records cache-like artifacts referenced anywhere in the import closure.",
        "",
        "Static import reachability is conservative: an imported helper may reference a cache path that the entrypoint never executes. Treat these findings as provenance boundaries, not automatic invalidation.",
        "",
        "## Summary",
        "",
        f"- Entry points audited: `{len(entrypoint_reports)}`",
    ]
    for status, count in sorted(counts.items()):
        lines.append(f"- `{status}`: `{count}`")
    lines.extend(["", "## Entry Points", ""])
    for item in entrypoint_reports:
        diag = item["diagnostic_or_partial_cache_artifacts"]
        clean = item["clean_manifest_cache_artifacts"]
        lines.append(f"### `{item['entrypoint']}`")
        lines.append(f"- Role: `{item['entrypoint_role']}`")
        lines.append(f"- Classification: `{item['classification']}`")
        lines.append(f"- Import-closure files: `{item['n_dependency_files']}`")
        if diag:
            short_diag = ", ".join(f"`{artifact}`" for artifact in diag[:8])
            if len(diag) > 8:
                short_diag += f", ... +{len(diag) - 8} more"
            lines.append(f"- Diagnostic/partial artifacts in closure: {short_diag}")
        else:
            lines.append("- Diagnostic/partial artifacts in closure: none")
        if clean:
            lines.append("- Clean-manifest artifacts in closure: " + ", ".join(f"`{artifact}`" for artifact in clean))
        else:
            lines.append("- Clean-manifest artifacts in closure: none")
        lines.append(f"- Interpretation: {item['interpretation']}")
        lines.append("")
    lines.extend(
        [
            "## Verdict",
            "",
            report["verdict"],
            "",
            f"Machine-readable report: `{OUT_JSON.relative_to(ROOT)}`",
            "",
        ]
    )
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")

    print(f"Wrote {OUT_JSON.relative_to(ROOT)}")
    print(f"Wrote {OUT_MD.relative_to(ROOT)}")
    print(json.dumps({"classification_counts": counts}, indent=2))


if __name__ == "__main__":
    main()
