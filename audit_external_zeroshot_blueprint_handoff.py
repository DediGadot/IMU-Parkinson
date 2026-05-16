#!/usr/bin/env python3
"""Audit the content-free all-route external zero-shot blueprint handoff."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pd_imu.datasets import external_schema_probe_specs
from pd_imu.experiments import SCHEMA_PROBE_ONLY_BLOCKED_ACTIONS


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
SCRIPT = ROOT / "scripts" / "write_external_zeroshot_blueprint_handoff.py"
HANDOFF_JSON = RESULTS / "external_zeroshot_blueprint_handoff_20260515.json"
HANDOFF_MD = RESULTS / "external_zeroshot_blueprint_handoff_20260515.md"
SCHEMA_HANDOFF_AUDIT = RESULTS / "external_schema_probe_handoff_audit_20260515.json"
TARGET_FREE_TEMPLATES_AUDIT = (
    RESULTS / "external_target_free_manifest_templates_audit_20260515.json"
)
FORMULA_SHA_TEMPLATES_AUDIT = RESULTS / "external_formula_sha_templates_audit_20260515.json"
ZEROSHOT_RESULT_TEMPLATES_AUDIT = RESULTS / "external_zeroshot_result_templates_audit_20260515.json"
PPMI_BLUEPRINT_AUDIT_SCRIPT = ROOT / "audit_ppmi_verily_zeroshot_blueprint.py"
PPMI_BLUEPRINT_AUDIT = RESULTS / "ppmi_verily_zeroshot_blueprint_audit_20260515.json"
OUT_JSON = RESULTS / "external_zeroshot_blueprint_handoff_audit_20260515.json"
OUT_MD = RESULTS / "external_zeroshot_blueprint_handoff_audit_20260515.md"

EXPECTED_ROUTE_IDS = [
    "ppmi_verily",
    "ppp_pd_vme",
    "watchpd",
    "cns_portugal_lobo",
    "hssayeni_mjff",
    "icicle_gait",
]
EXPECTED_TRACK_IDS = ["A", "B", "C", "D"]
EXPECTED_ANALYSIS_STEPS = [
    "approval_metadata_record",
    "read_only_schema_probe",
    "schema_probe_report_preflight",
    "schema_probe_metadata_record",
    "target_free_manifest_preflight",
    "formula_sha256_after_manifest_before_extraction_or_scoring",
    "zero_shot_external_validation",
    "aggregate_result_record_preflight_after_external_scoring",
    "route_only_grouped_sanity_if_zero_shot_fails_or_for_context",
    "fresh_augmentation_preregistration_only_after_zero_shot",
]
EXPECTED_NO_SEARCH_RULES = [
    "no scaffold before approved schema probe",
    "no cache extraction before schema-probe metadata recorded",
    "no external labels for zero-shot feature selection",
    "no PH/MFDFA column search on the external route",
    "no TopoFractal component-count search on the external route",
    "no K-search on the external route",
    "no adaptive stacking before zero-shot results",
    "no endpoint switching after external outcomes",
    "no canonical WearGait-PD T1/T3 update from external-only metrics",
]
EXPECTED_PPMI_LOCKED_FORMULA_COMPONENTS = [
    "small fixed TopoFractal PH/MFDFA branch",
    "canonical comparator",
    "separate fixed K=250 sklearn-GB branch for T3 only",
    "no omnibus feature expansion",
    "no cross-branch adaptive stacking before zero-shot results",
]
EXPECTED_PPMI_ROUTE_SPECIFIC_TRACKS = {
    "A": "weargait_trained_wrist_topofractal_zeroshot",
    "B": "weargait_trained_clinical_plus_wrist_zeroshot",
    "C": "ppmi_only_subject_grouped_sanity",
    "D": "augmentation_screen_after_zero_shot_only",
}
FORBIDDEN_SNIPPETS = [
    ".access_",
    "_submission.json",
    "_approval.json",
    "_schema_probe.json",
    "LOCAL_COMPLETED",
    "password",
    "api_key",
    "private_key",
    "raw sample",
    "raw rows",
]


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{rel(path)} must contain a JSON object")
    return payload


def run_cmd(args: list[str], *, timeout: int = 120) -> dict[str, Any]:
    proc = subprocess.run(
        args,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=timeout,
    )
    parsed: dict[str, Any] | None = None
    try:
        parsed = json.loads(proc.stdout)
    except json.JSONDecodeError:
        parsed = None
    return {
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "parsed": parsed,
    }


def forbidden_found(text: str) -> list[str]:
    lower = text.lower()
    return [snippet for snippet in FORBIDDEN_SNIPPETS if snippet.lower() in lower]


def check(name: str, passed: bool, evidence: dict[str, Any]) -> dict[str, Any]:
    return {"name": name, "passed": bool(passed), "evidence": evidence}


def track_ids(row: dict[str, Any]) -> list[str]:
    return [track.get("track_id") for track in row.get("tracks", []) if isinstance(track, dict)]


def expected_command_templates(route_id: str) -> dict[str, str]:
    commands = {
        "validate_schema_probe_report": (
            "uv run python scripts/validate_schema_probe_report.py "
            f"--route-id {route_id} "
            "--report <completed_schema_probe_report_path_outside_git>"
        ),
        "validate_target_free_manifest": (
            "uv run python scripts/validate_target_free_manifest.py "
            f"--route-id {route_id} "
            "--manifest <completed_target_free_manifest_path_outside_git>"
        ),
        "validate_formula_sha_record": (
            "uv run python scripts/validate_external_formula_sha_record.py "
            f"--route-id {route_id} "
            "--record <completed_formula_sha_record_path_outside_git>"
        ),
        "validate_zeroshot_result_record": (
            "uv run python scripts/validate_external_zeroshot_result_record.py "
            f"--route-id {route_id} "
            "--record <completed_external_zeroshot_result_record_path_outside_git>"
        ),
    }
    if route_id == "ppmi_verily":
        commands.update(
            {
                "validate_schema_probe_report": (
                    "uv run python scripts/validate_ppmi_verily_schema_probe_report.py "
                    "--report <completed_schema_probe_report_path_outside_git>"
                ),
                "validate_target_free_manifest": (
                    "uv run python scripts/validate_ppmi_verily_target_free_manifest.py "
                    "--manifest <completed_target_free_manifest_path_outside_git>"
                ),
            }
        )
    return commands


def expected_schema_validator(route_id: str) -> str:
    if route_id == "ppmi_verily":
        return "scripts/validate_ppmi_verily_schema_probe_report.py"
    return "scripts/validate_schema_probe_report.py"


def expected_target_free_validator(route_id: str) -> str:
    if route_id == "ppmi_verily":
        return "scripts/validate_ppmi_verily_target_free_manifest.py"
    return "scripts/validate_target_free_manifest.py"


def row_matches_spec(row: dict[str, Any], spec: Any) -> bool:
    return (
        row.get("id") == spec.route_id
        and row.get("name") == spec.name
        and tuple(row.get("required_grouping_keys") or ()) == spec.required_grouping_keys
        and tuple(row.get("required_target_columns") or ()) == spec.required_target_columns
        and tuple(row.get("required_sensor_modalities") or ())
        == spec.required_sensor_modalities
        and row.get("min_subjects") == spec.min_subjects
        and row.get("protected_access_required") == spec.protected_access_required
    )


def write_markdown(report: dict[str, Any]) -> None:
    lines = [
        "# External Zero-Shot Blueprint Handoff Audit - 2026-05-15",
        "",
        "This audits the generic zero-shot analysis-order handoff. It is not an approval, schema probe, completed manifest, preregistration, model result, or completion marker.",
        "",
        f"- Passed: `{report['passed']}`",
        f"- Decision: `{report['decision']}`",
        f"- Handoff JSON: `{report['handoff_json']}`",
        f"- Handoff Markdown: `{report['handoff_markdown']}`",
        f"- Route count: `{report['route_count']}`",
        f"- Hard failures: `{len(report['hard_failures'])}`",
        "",
        "## Checks",
        "",
    ]
    for row in report["checks"]:
        lines.append(f"- `{row['passed']}` {row['name']}")
    if report["hard_failures"]:
        lines.extend(["", "## Hard Failures", ""])
        for failure in report["hard_failures"]:
            lines.append(f"- {failure['name']}: {failure['evidence']}")
    else:
        lines.extend(["", "## Hard Failures", "", "- None."])
    lines.append("")
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    writer = run_cmd([sys.executable, str(SCRIPT)])
    ppmi_audit_proc = run_cmd([sys.executable, str(PPMI_BLUEPRINT_AUDIT_SCRIPT)])
    handoff = load_json(HANDOFF_JSON) if HANDOFF_JSON.exists() else {}
    schema_handoff_audit = load_json(SCHEMA_HANDOFF_AUDIT)
    target_free_templates_audit = load_json(TARGET_FREE_TEMPLATES_AUDIT)
    formula_sha_templates_audit = load_json(FORMULA_SHA_TEMPLATES_AUDIT)
    zeroshot_result_templates_audit = load_json(ZEROSHOT_RESULT_TEMPLATES_AUDIT)
    ppmi_blueprint_audit = load_json(PPMI_BLUEPRINT_AUDIT)
    md_text = HANDOFF_MD.read_text(encoding="utf-8") if HANDOFF_MD.exists() else ""
    specs = external_schema_probe_specs()
    routes = handoff.get("routes") or []
    route_ids = [row.get("id") for row in routes]
    route_by_id = {row.get("id"): row for row in routes}
    ppmi_route = route_by_id.get("ppmi_verily", {})
    ppmi_route_blueprint = ppmi_route.get("route_specific_blueprint") or {}
    boundary = handoff.get("content_boundary") or {}
    support = handoff.get("ppmi_specific_support") or {}
    combined_text = json.dumps(handoff, sort_keys=True) + "\n" + md_text + "\n" + writer["stdout"]
    found_forbidden = forbidden_found(combined_text)

    checks = [
        check(
            "writer command succeeds and writes both handoff outputs",
            writer["returncode"] == 0
            and (writer.get("parsed") or {}).get("json") == rel(HANDOFF_JSON)
            and (writer.get("parsed") or {}).get("markdown") == rel(HANDOFF_MD)
            and (writer.get("parsed") or {}).get("route_count") == 6
            and HANDOFF_JSON.exists()
            and HANDOFF_MD.exists(),
            {"returncode": writer["returncode"], "stdout": writer["stdout"][-800:]},
        ),
        check(
            "handoff covers six schema-probe routes in contract order",
            handoff.get("decision") == "external_zeroshot_blueprint_handoff_ready"
            and handoff.get("route_count") == 6
            and route_ids == EXPECTED_ROUTE_IDS
            and route_ids == [spec.route_id for spec in specs]
            and handoff.get("goal_complete") is False,
            {"route_ids": route_ids, "spec_route_ids": [spec.route_id for spec in specs]},
        ),
        check(
            "route rows mirror pd_imu schema-probe specs",
            all(row_matches_spec(route_by_id.get(spec.route_id, {}), spec) for spec in specs),
            {
                "route_contracts": {
                    spec.route_id: {
                        "row": route_by_id.get(spec.route_id, {}),
                        "spec": spec.to_dict(),
                    }
                    for spec in specs
                }
            },
        ),
        check(
            "every route has the locked shared analysis order and four tracks",
            all(
                row.get("analysis_order") == EXPECTED_ANALYSIS_STEPS
                and track_ids(row) == EXPECTED_TRACK_IDS
                and all(
                    "claim_boundary" in track and track.get("claim_boundary")
                    for track in row.get("tracks", [])
                    if isinstance(track, dict)
                )
                for row in routes
            ),
            {
                "analysis_order": handoff.get("analysis_order"),
                "track_ids_by_route": {row.get("id"): track_ids(row) for row in routes},
            },
        ),
        check(
            "every route links schema, manifest, formula, and result preflight artifacts",
            all(
                (commands := expected_command_templates(str(row.get("id"))))
                and row.get("supporting_artifacts", {}).get("schema_probe_handoff")
                == "results/external_schema_probe_handoff_20260515.md"
                and row.get("supporting_artifacts", {}).get("schema_report_validator")
                == expected_schema_validator(str(row.get("id")))
                and row.get("supporting_artifacts", {}).get(
                    "schema_report_validator_command"
                )
                == commands["validate_schema_probe_report"]
                and row.get("supporting_artifacts", {}).get("target_free_manifest_validator")
                == expected_target_free_validator(str(row.get("id")))
                and row.get("supporting_artifacts", {}).get(
                    "target_free_manifest_validator_command"
                )
                == commands["validate_target_free_manifest"]
                and row.get("supporting_artifacts", {}).get(
                    "target_free_manifest_template"
                )
                == (
                    "results/external_target_free_manifest_templates_20260515/"
                    f"{row.get('id')}_target_free_manifest_template.json"
                )
                and row.get("supporting_artifacts", {}).get("formula_sha_validator")
                == "scripts/validate_external_formula_sha_record.py"
                and row.get("supporting_artifacts", {}).get(
                    "formula_sha_validator_command"
                )
                == commands["validate_formula_sha_record"]
                and row.get("supporting_artifacts", {}).get("formula_sha_template")
                == (
                    "results/external_formula_sha_templates_20260515/"
                    f"{row.get('id')}_formula_sha_record_template.json"
                )
                and row.get("supporting_artifacts", {}).get("zeroshot_result_validator")
                == "scripts/validate_external_zeroshot_result_record.py"
                and row.get("supporting_artifacts", {}).get(
                    "zeroshot_result_validator_command"
                )
                == commands["validate_zeroshot_result_record"]
                and row.get("supporting_artifacts", {}).get("zeroshot_result_template")
                == (
                    "results/external_zeroshot_result_templates_20260515/"
                    f"{row.get('id')}_zeroshot_result_record_template.json"
                )
                and row.get("post_schema_command_templates") == commands
                for row in routes
            ),
            {
                "supporting_artifacts": {
                    row.get("id"): row.get("supporting_artifacts") for row in routes
                }
            },
        ),
        check(
            "markdown exposes executable schema-to-result preflight commands",
            "Formula-SHA template:" in md_text
            and "Formula-SHA validator:" in md_text
            and "Formula-SHA validator command:" in md_text
            and "Aggregate result template:" in md_text
            and "Aggregate result validator:" in md_text
            and "Aggregate result validator command:" in md_text
            and all(
                command in md_text
                for route_id in route_ids
                for command in expected_command_templates(str(route_id)).values()
            ),
            {
                "formula_template_present": "Formula-SHA template:" in md_text,
                "result_template_present": "Aggregate result template:" in md_text,
                "ppmi_schema_command_present": expected_command_templates("ppmi_verily")[
                    "validate_schema_probe_report"
                ]
                in md_text,
                "ppmi_target_free_command_present": expected_command_templates(
                    "ppmi_verily"
                )["validate_target_free_manifest"]
                in md_text,
            },
        ),
        check(
            "no-search and claim-boundary rules are explicit for all routes",
            handoff.get("locked_no_search_rules") == EXPECTED_NO_SEARCH_RULES
            and all(row.get("locked_no_search_rules") == EXPECTED_NO_SEARCH_RULES for row in routes)
            and all(
                "External rows may support transportability"
                in str(row.get("claim_boundary"))
                for row in routes
            ),
            {"locked_no_search_rules": handoff.get("locked_no_search_rules")},
        ),
        check(
            "blocked actions remain explicit until schema and manifest gates pass",
            all(
                tuple(row.get("blocked_until_schema_and_manifest_gates_pass") or ())
                == SCHEMA_PROBE_ONLY_BLOCKED_ACTIONS
                and "model run"
                in (row.get("blocked_until_schema_and_manifest_gates_pass") or [])
                and "canonical T1/T3 claim update"
                in (row.get("blocked_until_schema_and_manifest_gates_pass") or [])
                for row in routes
            ),
            {"blocked_until_schema_and_manifest": list(SCHEMA_PROBE_ONLY_BLOCKED_ACTIONS)},
        ),
        check(
            "schema and target-free handoff audits already pass",
            schema_handoff_audit.get("passed") is True
            and schema_handoff_audit.get("decision")
            == "external_schema_probe_handoff_ready"
            and schema_handoff_audit.get("route_count") == 6
            and target_free_templates_audit.get("passed") is True
            and target_free_templates_audit.get("decision")
            == "external_target_free_manifest_templates_ready"
            and target_free_templates_audit.get("route_count") == 6,
            {
                "schema_decision": schema_handoff_audit.get("decision"),
                "target_free_decision": target_free_templates_audit.get("decision"),
            },
        ),
        check(
            "formula-SHA template audit already passes",
            formula_sha_templates_audit.get("passed") is True
            and formula_sha_templates_audit.get("decision")
            == "external_formula_sha_templates_ready"
            and formula_sha_templates_audit.get("route_count") == 6
            and formula_sha_templates_audit.get("validator")
            == "scripts/validate_external_formula_sha_record.py",
            {
                "formula_decision": formula_sha_templates_audit.get("decision"),
                "hard_failures": formula_sha_templates_audit.get("hard_failures"),
            },
        ),
        check(
            "aggregate zero-shot result template audit already passes",
            zeroshot_result_templates_audit.get("passed") is True
            and zeroshot_result_templates_audit.get("decision")
            == "external_zeroshot_result_templates_ready"
            and zeroshot_result_templates_audit.get("route_count") == 6
            and zeroshot_result_templates_audit.get("validator")
            == "scripts/validate_external_zeroshot_result_record.py",
            {
                "result_decision": zeroshot_result_templates_audit.get("decision"),
                "hard_failures": zeroshot_result_templates_audit.get("hard_failures"),
            },
        ),
        check(
            "PPMI route-specific zero-shot blueprint remains wired and audited",
            support.get("route_id") == "ppmi_verily"
            and support.get("blueprint")
            == "results/ppmi_verily_zeroshot_blueprint_20260515.json"
            and support.get("blueprint_audit")
            == "results/ppmi_verily_zeroshot_blueprint_audit_20260515.json"
            and ppmi_audit_proc["returncode"] == 0
            and ppmi_blueprint_audit.get("passed") is True
            and ppmi_blueprint_audit.get("decision")
            == "ppmi_verily_zeroshot_blueprint_ready"
            and ppmi_blueprint_audit.get("not_a_model_result") is True
            and ppmi_blueprint_audit.get("not_access_approval") is True
            and ppmi_blueprint_audit.get("not_a_schema_probe_artifact") is True
            and ppmi_blueprint_audit.get("not_a_preregistration") is True
            and ppmi_blueprint_audit.get("goal_complete") is False,
            {
                "support": support,
                "ppmi_returncode": ppmi_audit_proc["returncode"],
                "ppmi_decision": ppmi_blueprint_audit.get("decision"),
                "ppmi_hard_failures": ppmi_blueprint_audit.get("hard_failures"),
            },
        ),
        check(
            "PPMI route row exposes exact route-specific blueprint branch contract",
            ppmi_route_blueprint.get("blueprint")
            == "results/ppmi_verily_zeroshot_blueprint_20260515.json"
            and ppmi_route_blueprint.get("blueprint_markdown")
            == "results/ppmi_verily_zeroshot_blueprint_20260515.md"
            and ppmi_route_blueprint.get("blueprint_audit")
            == "results/ppmi_verily_zeroshot_blueprint_audit_20260515.json"
            and ppmi_route_blueprint.get("must_use_for_exact_track_definitions") is True
            and ppmi_route_blueprint.get("required_locked_formula_components")
            == EXPECTED_PPMI_LOCKED_FORMULA_COMPONENTS
            and ppmi_route_blueprint.get("route_specific_track_names")
            == EXPECTED_PPMI_ROUTE_SPECIFIC_TRACKS
            and "formula_sha" in str(ppmi_route_blueprint.get("formula_sha_policy", ""))
            and "small fixed TopoFractal PH/MFDFA branch" in md_text
            and "separate fixed K=250 sklearn-GB branch for T3 only" in md_text
            and "Route-specific locked blueprint:" in md_text,
            {
                "ppmi_route_specific_blueprint": ppmi_route_blueprint,
                "expected_components": EXPECTED_PPMI_LOCKED_FORMULA_COMPONENTS,
                "expected_track_names": EXPECTED_PPMI_ROUTE_SPECIFIC_TRACKS,
            },
        ),
        check(
            "content boundary blocks completed/protected artifacts",
            handoff.get("not_a_submission_record") is True
            and handoff.get("not_access_approval") is True
            and handoff.get("not_a_schema_probe_artifact") is True
            and handoff.get("not_a_feature_manifest_artifact") is True
            and handoff.get("not_a_preregistration") is True
            and handoff.get("not_a_model_result") is True
            and boundary.get("completed_packets_included") is False
            and boundary.get("completed_emails_included") is False
            and boundary.get("protected_data_included") is False
            and boundary.get("approval_evidence_included") is False
            and boundary.get("schema_probe_artifacts_included") is False
            and boundary.get("feature_manifest_artifacts_included") is False
            and boundary.get("preregistration_artifacts_included") is False
            and boundary.get("record_paths_reported") is False
            and boundary.get("credentials_or_tokens_included") is False
            and boundary.get("target_values_included") is False
            and boundary.get("row_level_data_included") is False
            and boundary.get("feature_matrix_included") is False
            and boundary.get("model_outputs_included") is False,
            {"content_boundary": boundary},
        ),
        check(
            "handoff output does not expose private artifacts",
            not found_forbidden,
            {"forbidden_snippets_found": found_forbidden},
        ),
    ]
    hard_failures = [row for row in checks if not row["passed"]]
    report = {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "script": "audit_external_zeroshot_blueprint_handoff.py",
        "writer": "scripts/write_external_zeroshot_blueprint_handoff.py",
        "handoff_json": rel(HANDOFF_JSON),
        "handoff_markdown": rel(HANDOFF_MD),
        "source_schema_contract": "pd_imu.datasets.external_schema_probe_specs",
        "passed": not hard_failures,
        "decision": (
            "external_zeroshot_blueprint_handoff_ready"
            if not hard_failures
            else "external_zeroshot_blueprint_handoff_failed"
        ),
        "route_count": len(routes),
        "route_ids": route_ids,
        "checks": checks,
        "hard_failures": hard_failures,
        "not_a_submission_record": True,
        "not_access_approval": True,
        "not_a_schema_probe_artifact": True,
        "not_a_feature_manifest_artifact": True,
        "not_a_preregistration": True,
        "not_a_model_result": True,
        "protected_data_included": False,
        "credentials_or_tokens_included": False,
        "goal_complete": False,
    }
    OUT_JSON.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_markdown(report)
    print(
        json.dumps(
            {
                "passed": report["passed"],
                "decision": report["decision"],
                "hard_failure_count": len(hard_failures),
                "route_count": report["route_count"],
            },
            indent=2,
        )
    )
    if hard_failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
